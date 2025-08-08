import logging

import ckan.plugins as p
import ckan.logic as logic
from ckanext.hierarchy.model import GroupTreeNode
import ckan.authz as authz

log = logging.getLogger(__name__)
_get_or_bust = logic.get_or_bust


def get_visibility_from_group(group):
    try:
        v = (group.extras or {}).get("visibility")
        return v or "public"
    except Exception:
        return "public"


@logic.side_effect_free
def group_tree(context, data_dict):
    model = _get_or_bust(context, "model")
    group_type = data_dict.get("type", "group")

    # Check for sysadmin status
    is_sysadmin = False
    user_capacities = {}
    auth_user_obj = context.get("auth_user_obj")
    user = context.get("user")

    if user:
        log.error("Enters here as user")

        if authz.is_sysadmin(user):
            is_sysadmin = True
        else:
            # Only query capacities if not sysadmin
            user_id = auth_user_obj.id
            members = (
                model.Session.query(model.Member)
                .filter(
                    model.Member.table_name == "user",
                    model.Member.table_id == user_id,
                    model.Member.state == "active",
                )
                .all()
            )
            user_capacities = {m.group_id: m.capacity for m in members}

    return [
        _group_tree_branch(
            group,
            model=model,
            type=group_type,
            user_capacities=user_capacities,
            is_sysadmin=is_sysadmin,
        )
        for group in model.Group.get_top_level_groups(type=group_type)
    ]


@logic.side_effect_free
def group_tree_section(context, data_dict):
    """Returns the section of the group tree hierarchy which includes the given
    group, from the top-level group downwards.

    :param id: the id or name of the group to include in the tree
    :param include_parents: if false, starts from given group
    :param include_siblings: if false, excludes given group siblings
    :returns: the top GroupTreeNode of the tree section
    """
    model = _get_or_bust(context, "model")
    group_name_or_id = _get_or_bust(data_dict, "id")
    group = model.Group.get(group_name_or_id)

    # Check for sysadmin status
    is_sysadmin = False
    user_capacities = {}
    auth_user_obj = context.get("auth_user_obj")
    user = context.get("user")

    if user:
        if authz.is_sysadmin(user):
            is_sysadmin = True
        else:
            user_id = auth_user_obj.id
            members = (
                model.Session.query(model.Member)
                .filter(
                    model.Member.table_name == "user",
                    model.Member.table_id == user_id,
                    model.Member.state == "active",
                )
                .all()
            )
            user_capacities = {m.group_id: m.capacity for m in members}

    if group is None:
        raise p.toolkit.ObjectNotFound

    group_type = data_dict.get("type", "group")

    if group.type != group_type:
        how_type_was_set = (
            "was specified" if data_dict.get("type") else "is filtered by default"
        )
        raise p.toolkit.ValidationError(
            'Group type is "%s" not "%s" that %s'
            % (group.type, group_type, how_type_was_set)
        )
    include_parents = context.get("include_parents", True)
    include_siblings = context.get("include_siblings", True)

    if include_parents:
        root_group = (group.get_parent_group_hierarchy(type=group_type) or [group])[0]
    else:
        root_group = group

    if include_siblings or root_group == group:
        return _group_tree_branch(
            root_group,
            model=model,
            highlight_group_name=group.name,
            type=group_type,
            user_capacities=user_capacities,
            is_sysadmin=is_sysadmin,
        )
    else:
        section_subtree = _group_tree_branch(
            group,
            model=model,
            highlight_group_name=group.name,
            type=group_type,
            user_capacities=user_capacities,
            is_sysadmin=is_sysadmin,
        )
        return _nest_group_tree_list(
            group.get_parent_group_hierarchy(type=group_type),
            section_subtree,
            user_capacities=user_capacities,
            is_sysadmin=is_sysadmin,
        )


def _nest_group_tree_list(
    group_tree_list, group_tree_leaf, user_capacities=None, is_sysadmin=False
):
    """Returns a tree branch composed by nesting the groups in the list.

    :param group_tree_list: list of groups to build a tree, first is root
    :returns: the top GroupTreeNode of the tree
    """
    root_node = None
    last_node = None

    for group in group_tree_list:
        node_dict = {
            "id": group.id,
            "name": group.name,
            "title": group.title,
            "type": group.type,
            "visibility": get_visibility_from_group(group),
        }

        # Set capacity for sysadmin
        if is_sysadmin:
            node_dict["capacity"] = "admin"
        else:
            node_dict["capacity"] = user_capacities.get(group.id, "member")

        node = GroupTreeNode(node_dict)

        if not root_node:
            root_node = last_node = node
        else:
            last_node.add_child_node(node)
            last_node = node

    last_node.add_child_node(group_tree_leaf)

    return root_node


def _group_tree_branch(
    root_group,
    model,
    highlight_group_name=None,
    type="group",
    user_capacities=None,
    is_sysadmin=False,
):
    """Returns a branch of the group tree hierarchy, rooted in the given group.

    :param root_group_id: group object at the top of the part of the tree
    :param highlight_group_name: group name that is to be flagged 'highlighted'
    :returns: the top GroupTreeNode of the tree
    """
    nodes = {}
    root_dict = {
        "id": root_group.id,
        "name": root_group.name,
        "title": root_group.title,
        "type": root_group.type,
        "visibility": get_visibility_from_group(root_group),
    }
    if is_sysadmin:
        root_dict["capacity"] = "admin"
    else:
        root_dict["capacity"] = user_capacities.get(root_group.id)
    root_node = nodes[root_group.id] = GroupTreeNode(root_dict)
    if root_group.name == highlight_group_name:
        nodes[root_group.id].highlight()
        highlight_group_name = None
    for (
        group_id,
        group_name,
        group_title,
        parent_id,
    ) in root_group.get_children_group_hierarchy(type=type):
        child = model.Group.get(group_id)
        node_dict = {
            "id": group_id,
            "name": group_name,
            "title": group_title,
            "type": type,
            "visibility": get_visibility_from_group(child) if child else "public",
        }

        if is_sysadmin:
            node_dict["capacity"] = "admin"
        else:
            capacity = user_capacities.get(group_id)

            parent_node = nodes[parent_id]
            parent_capacity = parent_node.get("capacity")

            if capacity is None:
                capacity = parent_capacity or root_dict["capacity"]

            node_dict["capacity"] = capacity

        node = GroupTreeNode(node_dict)
        nodes[parent_id].add_child_node(node)
        if highlight_group_name and group_name == highlight_group_name:
            node.highlight()
        nodes[group_id] = node

    return root_node
