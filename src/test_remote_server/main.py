
from fastmcp import FastMCP
import os
import json
from decimal import Decimal
from pathlib import Path
import psycopg

from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load local settings from the project's .env file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

CATEGORIES_PATH = PROJECT_ROOT / "categories.json"

DB_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "expense_tracker"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD"),
}

mcp = FastMCP("TEST_REMOTE_SERVER")


def get_connection():
    """Open a PostgreSQL connection using settings from the .env file."""
    if not DB_CONFIG["password"]:
        raise RuntimeError(
            "PostgreSQL password is missing. Set PGPASSWORD in the project's .env file."
        )
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


def json_safe(value):
    """Convert PostgreSQL Decimal values to JSON-friendly numbers."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


# ---------------- DATABASE INITIALIZATION ----------------

def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id BIGSERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                category TEXT NOT NULL,
                subcategory TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credits (
                id BIGSERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                category TEXT NOT NULL DEFAULT 'Credit',
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )


# ---------------- HELPER: SEARCH EXPENSES ----------------

def find_matching_expenses(
    expense_id=None,
    match_amount=None,
    match_category=None,
    match_note=None,
    match_date=None,
):
    """Find expenses using one or more identifying fields."""
    conditions = []
    params = []

    if expense_id is not None:
        conditions.append("id = %s")
        params.append(expense_id)
    if match_amount is not None:
        conditions.append("amount = %s")
        params.append(match_amount)
    if match_category:
        conditions.append("category ILIKE %s")
        params.append(f"%{match_category}%")
    if match_note:
        conditions.append("note ILIKE %s")
        params.append(f"%{match_note}%")
    if match_date:
        conditions.append("date = %s")
        params.append(match_date)

    if not conditions:
        return []

    query = """
        SELECT id, date, amount, category, subcategory, note
        FROM expenses
        WHERE """ + " AND ".join(conditions) + " ORDER BY id ASC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return json_safe(rows)


# ---------------- 1. ADD EXPENSE ----------------

@mcp.tool()
def add_expense(date: str, amount: float, category: str, subcategory: str = "", note: str = ""):
    """Add a new expense."""
    if amount <= 0:
        return {"status": "error", "message": "Amount must be positive."}

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO expenses (date, amount, category, subcategory, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (date, amount, category, subcategory, note),
        ).fetchone()

    return {"status": "ok", "id": row["id"], "message": "Expense added successfully."}


# ---------------- 2. LIST EXPENSES ----------------

@mcp.tool()
def list_expenses(start_date: str, end_date: str):
    """List expenses within an inclusive date range. Use YYYY-MM-DD dates."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE date BETWEEN %s AND %s
            ORDER BY id ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return json_safe(rows)


# ---------------- 3. SUMMARIZE EXPENSES ----------------

@mcp.tool()
def summarize(start_date: str, end_date: str, category: str | None = None):
    """Summarize spending by category within a date range."""
    query = """
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE date BETWEEN %s AND %s
    """
    params = [start_date, end_date]
    if category:
        query += " AND category = %s"
        params.append(category)
    query += " GROUP BY category ORDER BY category ASC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return json_safe(rows)


# ---------------- 4. SEARCH EXPENSES ----------------

@mcp.tool()
def search_expenses(
    expense_id: int | None = None,
    amount: float | None = None,
    category: str | None = None,
    note: str | None = None,
    date: str | None = None,
):
    """Search expenses by ID, amount, category, note, or date."""
    matches = find_matching_expenses(
        expense_id=expense_id,
        match_amount=amount,
        match_category=category,
        match_note=note,
        match_date=date,
    )
    if not matches:
        return {"status": "not_found", "count": 0, "matches": []}
    return {"status": "ok", "count": len(matches), "matches": matches}


# ---------------- 5. EDIT EXPENSE ----------------

@mcp.tool()
def edit_expense(
    expense_id: int,
    match_amount: float | None = None,
    match_category: str | None = None,
    match_note: str | None = None,
    match_date: str | None = None,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None,
):
    """Edit an expense by ID or existing details. If several match, nothing changes."""
    matches = find_matching_expenses(
        expense_id=expense_id,
        match_amount=match_amount,
        match_category=match_category,
        match_note=match_note,
        match_date=match_date,
    )
    if not matches:
        return {"status": "not_found", "message": "No matching expense found."}
    if len(matches) > 1:
        return {
            "status": "needs_clarification",
            "message": "Multiple expenses match. Nothing was edited. Select one by ID or more details.",
            "matches": matches,
        }

    updates = {
        key: value
        for key, value in {
            "date": date,
            "amount": amount,
            "category": category,
            "subcategory": subcategory,
            "note": note,
        }.items()
        if value is not None
    }
    if not updates:
        return {"status": "error", "message": "Provide at least one field to update."}
    if amount is not None and amount <= 0:
        return {"status": "error", "message": "Amount must be positive."}

    selected_id = matches[0]["id"]
    set_clause = ", ".join(f"{field} = %s" for field in updates)
    values = list(updates.values()) + [selected_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE expenses SET {set_clause} WHERE id = %s", values)

    return {
        "status": "ok",
        "id": selected_id,
        "updated_fields": list(updates.keys()),
        "message": f"Expense ID {selected_id} updated successfully.",
    }


# ---------------- 6. DELETE EXPENSE ----------------

@mcp.tool()
def delete_expense(
    expense_id: int,
    amount: float | None = None,
    category: str | None = None,
    note: str | None = None,
    date: str | None = None,
):
    """Delete an expense by ID or details. If several match, nothing is deleted."""
    matches = find_matching_expenses(
        expense_id=expense_id,
        match_amount=amount,
        match_category=category,
        match_note=note,
        match_date=date,
    )
    if not matches:
        return {"status": "not_found", "message": "No matching expense found."}
    if len(matches) > 1:
        return {
            "status": "needs_clarification",
            "message": "Multiple expenses match. Nothing was deleted. Select one by ID or more details.",
            "matches": matches,
        }

    selected = matches[0]
    with get_connection() as conn:
        conn.execute("DELETE FROM expenses WHERE id = %s", (selected["id"],))
    return {
        "status": "ok",
        "id": selected["id"],
        "deleted_expense": selected,
        "message": f"Expense ID {selected['id']} deleted successfully.",
    }


# ---------------- 7. RECORD CREDIT ----------------

@mcp.tool()
def credit_expense(date: str, amount: float,category: str = "Credit",note: str = "",
):
    """Record money received in the separate credits table; credits are not spending."""
    if amount <= 0:
        return {"status": "error", "message": "Credit amount must be positive."}

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO credits (date, amount, category, note)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (date, amount, category, note),
        ).fetchone()
    return {
        "status": "ok",
        "credit_id": row["id"],
        "amount": amount,
        "message": "Credit recorded successfully.",
    }


# ---------------- 8. LIST CREDITS ----------------

@mcp.tool()
def list_credits(start_date: str, end_date: str):
    """List money received within an inclusive date range. Use YYYY-MM-DD dates."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, date, amount, category, note
            FROM credits
            WHERE date BETWEEN %s AND %s
            ORDER BY id ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return json_safe(rows)



# ---------------- LIST CATEGORIES TOOL ----------------

@mcp.tool()
def list_categories():
    """Return all expense categories and their subcategories."""
    if not CATEGORIES_PATH.exists():
        return {"status": "error", "message": "categories.json was not found."}

    with open(CATEGORIES_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


# ---------------- RUN SERVER ----------------


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
