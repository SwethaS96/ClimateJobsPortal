"""Standalone repository test script.

This script exercises the organization repository using the project's
configured SQLite database (via `database.connection.get_connection()`). It is
designed to be run directly (not via pytest) and prints PASS/FAIL output for
each verification step.
"""
from typing import Any

import tests.mock_data as mock_data
from database.repositories import organization_repository


def print_result(step: str, passed: bool, info: Any = None) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {step}")
    if info is not None:
        print("  ->", info)


def main() -> None:
    print("=== Repository Test ===")

    # 1) Insert ORGANIZATION_1
    try:
        org_id = organization_repository.insert_organization(**mock_data.ORGANIZATION_1)
        insert_ok = isinstance(org_id, int) and org_id > 0
        print_result("Insert organization", insert_ok, f"id={org_id}")
    except Exception as exc:  # noqa: BLE001 - explicit top-level script handling
        print_result("Insert organization", False, exc)
        return

    # 2) Retrieve by id
    try:
        row = organization_repository.get_organization_by_id(org_id)
        exists = row is not None
        print_result("Get organization by id", exists, dict(row) if row is not None else None)
    except Exception as exc:
        print_result("Get organization by id", False, exc)
        return

    # 3) Retrieve all organizations
    try:
        all_orgs = organization_repository.get_all_organizations()
        many_ok = isinstance(all_orgs, list) and len(all_orgs) >= 1
        print_result("Get all organizations", many_ok, f"total={len(all_orgs)}")
        if many_ok:
            print("Retrieved organization:")
            first = all_orgs[0]
            print(dict(first))
    except Exception as exc:
        print_result("Get all organizations", False, exc)
        return


if __name__ == "__main__":
    main()
