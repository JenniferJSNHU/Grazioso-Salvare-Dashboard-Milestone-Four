"""Copy a limited set of local shelter records to the isolated Atlas demo database."""

from getpass import getpass
from pymongo import MongoClient, ReplaceOne
from animal_service import rescue_query

# read the Atlas URI privately instead of storing credentials in code
atlas_uri = getpass("Paste the Atlas connection URI (hidden): ").strip()
if not atlas_uri.startswith(("mongodb+srv://", "mongodb://")):
    raise SystemExit("Invalid connection string.")

# connect to the local source and remote demo database
local = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=10000)
atlas = MongoClient(atlas_uri, serverSelectionTimeoutMS=15000)
local.admin.command("ping")
atlas.admin.command("ping")

# use the animals collection in both databases
source = local["aac"]["animals"]
target = atlas["aac"]["animals"]
if source.count_documents({}) == 0:
    raise SystemExit("Local aac.animals database has no records.")

# collect general records and rescue candidates without duplicate IDs
records = {}
queries = [
    {},
    rescue_query("water"),
    rescue_query("mountain"),
    rescue_query("disaster"),
]
limits = [750, 100, 100, 100]
for query, limit in zip(queries, limits):
    for record in source.find(query, {"_id": 0}).limit(limit):
        animal_id = record.get("animal_id")
        if isinstance(animal_id, str) and animal_id.strip():
            records[animal_id] = record

if not records:
    raise SystemExit("No usable animal_id records found.")

# write records in batches and update existing IDs instead of duplicating them
items = list(records.values())
for offset in range(0, len(items), 200):
    batch = items[offset : offset + 200]
    target.bulk_write(
        [
            ReplaceOne({"animal_id": item["animal_id"]}, item, upsert=True)
            for item in batch
        ],
        ordered=False,
    )
# report the final Atlas count without modifying local data
print(f"Ready: {target.count_documents({})} records in Atlas aac.animals")
print("The local MongoDB records were not changed.")
local.close()
atlas.close()
