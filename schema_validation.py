"""MongoDB document validation rules for the shelter animals collection."""

from animal_service import REQUIRED_FIELDS


# accept BSON integer, long, decimal, and double values for numeric fields
NUMERIC_TYPES = ["int", "long", "double", "decimal"]

# enforce staff-form field types without rejecting extra legacy AAC fields
ANIMAL_JSON_SCHEMA = {
    "bsonType": "object",
    "required": list(REQUIRED_FIELDS),
    "properties": {
        "animal_id": {"bsonType": "string", "minLength": 1},
        "name": {"bsonType": "string"},
        "animal_type": {"bsonType": "string", "minLength": 1},
        "breed": {"bsonType": "string", "minLength": 1},
        "sex_upon_outcome": {"bsonType": "string", "minLength": 1},
        "age_upon_outcome_in_weeks": {
            "bsonType": NUMERIC_TYPES,
            "minimum": 0,
        },
        "location_lat": {
            "bsonType": NUMERIC_TYPES,
            "minimum": -90,
            "maximum": 90,
        },
        "location_long": {
            "bsonType": NUMERIC_TYPES,
            "minimum": -180,
            "maximum": 180,
        },
    },
}

# validate new documents but avoid blocking edits to older invalid imports
ANIMAL_VALIDATOR = {"$jsonSchema": ANIMAL_JSON_SCHEMA}
SCHEMA_LEVEL = "moderate"
SCHEMA_ACTION = "error"


def count_legacy_schema_violations(collection):
    """Count existing records that do not satisfy the proposed validator."""
    # use a read-only MongoDB query to check legacy records
    return collection.count_documents({"$nor": [ANIMAL_VALIDATOR]})
