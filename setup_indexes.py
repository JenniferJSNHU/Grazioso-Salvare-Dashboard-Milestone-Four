"""Create the planned MongoDB indexes and record before-and-after query plans."""

from pathlib import Path

from dotenv import load_dotenv

# load existing local configuration without storing connection details in code
load_dotenv(Path(__file__).resolve().parent / ".env")

from CRUD_Python_Module import AnimalShelter
from benchmarks.benchmark_database import capture_query_plans, save_index_comparison


# run index creation explicitly, never when the web dashboard starts
def main():
    shelter = AnimalShelter()
    try:
        # confirm database access before reading query plans
        shelter.client.admin.command("ping")
        collection = shelter.collection
        old_indexes = sorted(collection.index_information())
        record_count = collection.count_documents({})
        # identify the selected server without exposing credentials
        server_address = shelter.client.address
        print("MongoDB server:", server_address[0] if server_address else "connected cluster")
        print(f"Target database: {collection.database.name}.{collection.name}")
        print(f"Animal records: {record_count:,}")
        if not record_count:
            raise SystemExit("The selected database has no records; indexes were not changed.")
        if input("Create planned indexes on this collection? [y/N]: ").strip().lower() != "y":
            raise SystemExit("Index setup cancelled; no changes made.")

        # capture baseline plans before creating any new indexes
        before = capture_query_plans(collection)

        # indexes are idempotent and do not edit existing animal records
        created = shelter.ensure_indexes()
        new_indexes = sorted(collection.index_information())

        # capture equivalent query plans after index creation
        after = capture_query_plans(collection)
        report_path = save_index_comparison(
            collection, before, after, old_indexes, new_indexes
        )

        print("New indexes:", ", ".join(created) if created else "already present")
        print("Indexes verified:", ", ".join(new_indexes))
        print("Query-plan comparison saved:", report_path)
        print("Animal records were not modified.")
    finally:
        # release the database connection when setup finishes
        shelter.client.close()


if __name__ == "__main__":
    main()
