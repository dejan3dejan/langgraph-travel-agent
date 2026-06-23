"""Unit tests for trip collaboration authorization. Pure decision rules, no DB.

These cover the security boundary: who may read versus edit a trip, decided from already-fetched
ownership and membership values. The DB resolvers that feed these are exercised in test_collab_api.
"""

from api.authz import access_role, role_can_edit, role_can_read


def test_owner_gets_owner_role():
    assert access_role(owner_id="u1", member_role=None, user_id="u1") == "owner"


def test_editor_member_gets_editor_role():
    assert access_role(owner_id="u1", member_role="editor", user_id="u2") == "editor"


def test_viewer_member_gets_viewer_role():
    assert access_role(owner_id="u1", member_role="viewer", user_id="u2") == "viewer"


def test_non_member_gets_no_role():
    assert access_role(owner_id="u1", member_role=None, user_id="u2") is None


def test_anonymous_requester_gets_no_role():
    # a request with no authenticated user can never own or be a member
    assert access_role(owner_id="u1", member_role=None, user_id=None) is None


def test_owner_wins_over_a_stray_membership_row():
    # if the owner somehow also has a viewer row, ownership still grants full access
    assert access_role(owner_id="u1", member_role="viewer", user_id="u1") == "owner"


def test_unknown_role_string_is_rejected():
    # only the two known roles grant access; a garbage value must not
    assert access_role(owner_id="u1", member_role="admin", user_id="u2") is None


def test_role_can_edit_allows_owner_and_editor_only():
    assert role_can_edit("owner") is True
    assert role_can_edit("editor") is True
    assert role_can_edit("viewer") is False
    assert role_can_edit(None) is False


def test_role_can_read_allows_any_role_but_not_none():
    assert role_can_read("owner") is True
    assert role_can_read("editor") is True
    assert role_can_read("viewer") is True
    assert role_can_read(None) is False
