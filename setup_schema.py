"""Inspect and explicitly enable MongoDB schema validation for aac.animals."""

from pathlib import Path

from dotenv import load_dotenv

# load local database settings without including credentials in the repository
load_dotenv(Path(__file__).resolve().parent / ".env")

from CRUD_Python_Module import AnimalShelter
from schema_validation import (
    ANIMAL_VALIDATOR,
    SCHEMA_ACTION,
    SCHEMA_LEVEL,
    count_legacy_schema_violations,
)


# perform a read-only preflight before requesting any database change
def main():
    shelter = AnimalShelter()
    try:
        shelter.client.admin.command("ping")
        collection = shelter.collection
        address = shelter.client.address
        print("MongoDB server:", address[0] if address else "connected cluster")
        print(f"Target collection: {collection.database.name}.{collection.name}")
        print(f"Animal records: {collection.count_documents({}):,}")

        # do not override collection rules installed outside this project
        options = collection.options()
        existing = options.get("validator")
        if existing:
            if (
                existing == ANIMAL_VALIDATOR
                and options.get("validationLevel", "strict") == SCHEMA_LEVEL
                and options.get("validationAction", "error") == SCHEMA_ACTION
            ):
                print("The planned MongoDB schema validation is already active.")
                return
            raise SystemExit("A different validator already exists. No changes made.")

        # count legacy violations without reading or changing individual records
        invalid_count = count_legacy_schema_violations(collection)
        print(f"Existing records outside the proposed schema: {invalid_count:,}")
        if invalid_count:
            print("Moderate validation preserves updates to these legacy records.")
        print("New invalid records will be rejected after schema setup.")
        print("No existing animal records will be modified by this operation.")

        # require explicit confirmation before changing database collection settings
        choice = input("Enable the planned validator on this collection? [y/N]: ")
        if choice.strip().lower() != "y":
            print("Schema setup cancelled; no changes made.")
            return

        applied = shelter.ensure_schema_validation()
        verified = collection.options()
        if (
            verified.get("validator") != ANIMAL_VALIDATOR
            or verified.get("validationLevel") != SCHEMA_LEVEL
            or verified.get("validationAction") != SCHEMA_ACTION
        ):
            raise RuntimeError("MongoDB did not report the requested schema settings.")
        print("MongoDB schema validation enabled." if applied else "Schema already active.")
        print("Confirmed: validationLevel=moderate, validationAction=error")
        print("No animal records were modified.")
    finally:
        # close the database connection after the setup command finishes
        shelter.client.close()


if __name__ == "__main__":
    main()
