"""Business rules for Grazioso Salvare animal records.

This module does not connect to MongoDB or define the Dash interface.
The dashboard can use these functions before calling the CRUD module.
"""

from math import isfinite
import re

# rescue criteria retained from the original CS 340 dashboard
RESCUE_QUERIES = {
    "water": {
        "animal_type": "Dog",
        "breed": {
            "$regex": "Labrador Retriever|Chesapeake Bay Retriever|Newfoundland",
            "$options": "i",
        },
        "sex_upon_outcome": "Intact Female",
        "age_upon_outcome_in_weeks": {"$gte": 26, "$lte": 156},
    },
    "mountain": {
        "animal_type": "Dog",
        "breed": {
            "$regex": "German Shepherd|Alaskan Malamute|Old English Sheepdog|Siberian Husky|Rottweiler",
            "$options": "i",
        },
        "sex_upon_outcome": "Intact Male",
        "age_upon_outcome_in_weeks": {"$gte": 26, "$lte": 156},
    },
    "disaster": {
        "animal_type": "Dog",
        "breed": {
            "$regex": "Doberman Pinscher|German Shepherd|Golden Retriever|Bloodhound|Rottweiler",
            "$options": "i",
        },
        "sex_upon_outcome": "Intact Male",
        "age_upon_outcome_in_weeks": {"$gte": 20, "$lte": 300},
    },
}

# require these fields when creating a new animal
REQUIRED_FIELDS = (
    "animal_id",
    "animal_type",
    "breed",
    "sex_upon_outcome",
    "age_upon_outcome_in_weeks",
)

# allow only the fields supported by the staff forms
TEXT_FIELDS = {"animal_id", "name", "animal_type", "breed", "sex_upon_outcome"}
NUMBER_FIELDS = {"age_upon_outcome_in_weeks", "location_lat", "location_long"}
ALLOWED_FIELDS = TEXT_FIELDS | NUMBER_FIELDS


# return the criteria for a rescue type or clear the filter
def rescue_query(category):
    """Return the MongoDB filter for a rescue category."""
    if category in ("reset", None):
        return {}
    if category not in RESCUE_QUERIES:
        raise ValueError("Unknown rescue category.")
    return RESCUE_QUERIES[category].copy()


# allow table searches only on displayed database fields
TABLE_FILTER_FIELDS = {
    "animal_id",
    "name",
    "animal_type",
    "breed",
    "sex_upon_outcome",
    "age_upon_outcome_in_weeks",
}


# translate dash column filters into validated mongodb queries
def build_table_query(rescue_type, filter_query):
    query = rescue_query(rescue_type)
    if not filter_query:
        return query

    # match supported operators without treating user text as query syntax
    operator_pattern = (
        r"icontains|scontains|contains|ieq|seq|eq|ne|ge|gt|le|lt|>=|<=|!=|>|<|="
    )
    pattern = re.compile(
        r"^\{([a-z_]+)\}\s*(" + operator_pattern + r")\s*(.*?)\s*$"
    )
    conditions = []

    # combine filters from multiple columns using AND
    for expression in filter_query.split(" && "):
        match = pattern.fullmatch(expression.strip())
        if match is None:
            return {"_id": {"$exists": False}}

        field, operator, value = match.groups()
        if field not in TABLE_FILTER_FIELDS:
            return {"_id": {"$exists": False}}

        # remove surrounding quote characters from dash filter values
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not value or len(value) > 256:
            return {"_id": {"$exists": False}}

        if field == "age_upon_outcome_in_weeks":
            # compare age as a number rather than text
            try:
                number = float(value)
            except ValueError:
                return {"_id": {"$exists": False}}
            if not isfinite(number):
                return {"_id": {"$exists": False}}
            comparisons = {
                "=": "$eq", "eq": "$eq", "ieq": "$eq", "seq": "$eq",
                "ne": "$ne", "!=": "$ne", "ge": "$gte", ">=": "$gte",
                "gt": "$gt", ">": "$gt", "le": "$lte", "<=": "$lte",
                "lt": "$lt", "<": "$lt",
            }
            if operator not in comparisons:
                return {"_id": {"$exists": False}}
            conditions.append({field: {comparisons[operator]: number}})
        else:
            # escape special characters to prevent regex injection
            escaped = re.escape(value)
            if operator in ("=", "eq", "ieq", "seq"):
                escaped = f"^{escaped}$"
            elif operator in ("ne", "!="):
                escaped = f"^{escaped}$"
            elif operator not in ("contains", "icontains", "scontains"):
                return {"_id": {"$exists": False}}
            criterion = {"$regex": escaped}
            if operator not in ("scontains", "seq"):
                criterion["$options"] = "i"
            if operator in ("ne", "!="):
                conditions.append({field: {"$not": criterion}})
            else:
                conditions.append({field: criterion})

    # apply table searches alongside the existing rescue filter
    return {"$and": [query, *conditions]} if conditions else query


# check staff form data before any database write
def validate_animal(record, *, updating=False):
    """Validate fields supplied by a staff form.

    Returns a sanitized copy. Raises ValueError with a useful message when
    input is missing, malformed, or contains unsupported fields.
    Authentication/authorization must be enforced separately on the server.
    """
    if not isinstance(record, dict) or not record:
        raise ValueError("Provide animal record fields.")

    # block unexpected fields before processing the record
    unsupported = set(record) - ALLOWED_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported fields: {', '.join(sorted(unsupported))}.")

    # keep animal IDs stable so records remain identifiable
    if updating and "animal_id" in record:
        raise ValueError("Animal ID cannot be changed.")

    if not updating:
        missing = [key for key in REQUIRED_FIELDS if key not in record]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}.")

    # normalize text and validate numeric input one field at a time
    cleaned = {}
    for key, value in record.items():
        if key in TEXT_FIELDS:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text.")
            value = value.strip()
            if key != "name" and not value:
                raise ValueError(f"{key} cannot be empty.")
        elif key in NUMBER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number.")
            if not isfinite(value):
                raise ValueError(f"{key} must be finite.")
            if key == "age_upon_outcome_in_weeks" and value < 0:
                raise ValueError("Age cannot be negative.")
            if key == "location_lat" and not -90 <= value <= 90:
                raise ValueError("Latitude must be between -90 and 90.")
            if key == "location_long" and not -180 <= value <= 180:
                raise ValueError("Longitude must be between -180 and 180.")
        cleaned[key] = value

    # require a complete coordinate pair for accurate mapping
    if ("location_lat" in cleaned) != ("location_long" in cleaned):
        raise ValueError("Latitude and longitude must be provided together.")

    return cleaned
