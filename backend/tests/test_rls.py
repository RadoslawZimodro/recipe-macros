"""Row-Level Security and privileges, tested at the database level as the `app_user` role.

The API tests only prove the endpoints filter correctly. These prove the DATABASE itself
refuses to leak or accept foreign rows, even for raw SQL that forgets a WHERE clause.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import SessionLocal, engine, set_tenant
from tests.test_recipes import create

_SET_TENANT = text("SELECT set_config('app.current_user_id', :u, true)")
_NEW_STEP = text(
    "INSERT INTO recipe_steps (recipe_id, user_id, position, instruction) VALUES (:r, :u, 9, 'x')"
)


@contextmanager
def as_tenant(user_id):
    """A transaction as app_user with the RLS tenant set, like get_current_user does."""
    with engine.begin() as conn:
        if user_id is not None:
            conn.execute(_SET_TENANT, {"u": str(user_id)})
        yield conn


def count(conn, table):
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.fixture
def recipes(alice, bob):
    """Alice owns two recipes, Bob one; each has two steps and three ingredient lines."""
    return create(alice, title="A1"), create(alice, title="A2"), create(bob, title="B1")


def test_app_role_is_not_privileged(admin_db):
    row = admin_db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_user'")
    ).one()

    assert tuple(row) == (False, False)


# --- reads ---
def test_without_a_tenant_nothing_is_visible(recipes):
    with as_tenant(None) as conn:
        assert count(conn, "recipes") == 0
        assert count(conn, "recipe_steps") == 0
        assert count(conn, "recipe_ingredients") == 0


def test_a_tenant_sees_only_its_own_rows_even_with_a_bare_select(alice, bob, recipes):
    with as_tenant(alice.user_id) as conn:
        assert count(conn, "recipes") == 2
        assert count(conn, "recipe_steps") == 4
        assert count(conn, "recipe_ingredients") == 6
        owners = conn.execute(text("SELECT DISTINCT user_id FROM recipes")).scalars().all()
        assert owners == [alice.user_id]

    with as_tenant(bob.user_id) as conn:
        assert count(conn, "recipes") == 1


def test_the_tenant_does_not_leak_into_the_next_transaction(alice, recipes):
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(_SET_TENANT, {"u": str(alice.user_id)})
            assert count(conn, "recipes") == 2
        with conn.begin():  # same pooled connection, new transaction: the context is gone
            assert count(conn, "recipes") == 0


def test_orm_session_keeps_its_tenant_across_commits(alice, recipes):
    with SessionLocal() as session:
        set_tenant(session, alice.user_id)
        assert session.scalar(text("SELECT count(*) FROM recipes")) == 2
        session.commit()  # ends the transaction; the next one must re-apply the tenant
        assert session.scalar(text("SELECT count(*) FROM recipes")) == 2


# --- writes ---
def test_cannot_insert_a_recipe_for_another_user(alice, bob):
    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(bob.user_id) as conn:
        conn.execute(
            text("INSERT INTO recipes (user_id, title) VALUES (:u, 'podrzucony')"),
            {"u": alice.user_id},
        )


def test_cannot_update_or_delete_another_users_rows(alice, bob, recipes):
    with as_tenant(bob.user_id) as conn:
        updated = conn.execute(
            text("UPDATE recipes SET title = 'hacked' WHERE user_id = :u"), {"u": alice.user_id}
        )
        deleted = conn.execute(
            text("DELETE FROM recipe_steps WHERE user_id = :u"), {"u": alice.user_id}
        )
        assert updated.rowcount == 0 and deleted.rowcount == 0

    with as_tenant(alice.user_id) as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM recipes WHERE title = 'hacked'")).scalar_one()
            == 0
        )
        assert count(conn, "recipe_steps") == 4


def test_cannot_move_a_row_to_another_tenant(alice, bob, recipes):
    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(alice.user_id) as conn:
        conn.execute(text("UPDATE recipes SET user_id = :b"), {"b": bob.user_id})


def test_a_child_cannot_belong_to_another_user_than_its_recipe(alice, bob, recipes):
    # Bob adds a step to Alice's recipe, claiming it as his own: RLS lets the row through
    # (user_id matches Bob), but the composite FK (recipe_id, user_id) -> recipes(id, user_id)
    # finds no such pair.
    with pytest.raises(DBAPIError, match="foreign key"), as_tenant(bob.user_id) as conn:
        conn.execute(_NEW_STEP, {"r": recipes[0]["id"], "u": bob.user_id})


def test_the_composite_foreign_key_holds_even_for_the_owner_role(bob, admin_db, recipes):
    with pytest.raises(DBAPIError, match="foreign key"):
        admin_db.execute(_NEW_STEP, {"r": recipes[0]["id"], "u": bob.user_id})


# --- shared catalog and privileges ---
def test_the_shared_catalog_is_read_only_for_the_app_role(alice, admin_db):
    insert = (
        "INSERT INTO ingredients (user_id, canonical_name, kcal_per_100g, protein_per_100g, "
        "fat_per_100g, carbs_per_100g, source) VALUES (NULL, :name, 0, 0, 0, 0, 'off')"
    )
    admin_db.execute(text(insert), {"name": "Sól"})
    admin_db.commit()

    with as_tenant(alice.user_id) as conn:
        assert count(conn, "ingredients") == 1  # readable
    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(alice.user_id) as conn:
        conn.execute(text(insert), {"name": "Podrzucony"})
    # No UPDATE privilege at all, so editing a shared product is refused outright.
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        as_tenant(alice.user_id) as conn,
    ):
        conn.execute(text("UPDATE ingredients SET kcal_per_100g = 900"))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE units SET kind = 'mass' WHERE code = 'ml'",
        "DELETE FROM units",
        "INSERT INTO units (code, kind) VALUES ('bucket', 'volume')",
        "DELETE FROM recipes",  # recipes are soft-deleted only
        "SELECT * FROM alembic_version",
    ],
)
def test_least_privilege_for_the_app_role(statement):
    with pytest.raises(ProgrammingError, match="permission denied"), as_tenant(1) as conn:
        conn.execute(text(statement))
