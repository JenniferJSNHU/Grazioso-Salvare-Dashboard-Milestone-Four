from pymongo import ASCENDING, IndexModel, MongoClient
import os


# manage database operations for animal shelter records
class AnimalShelter:
    """CRUD operations for the AAC MongoDB animals collection."""

    # initialize the mongodb connection using supplied credentials
    def __init__(self):
        """Connect to the local MongoDB database."""
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(mongo_uri)
        self.database = self.client["aac"]
        self.collection = self.database["animals"]

    # create compound indexes for pagination, rescue queries, and column sorting
    def ensure_indexes(self):
        """Create the approved dashboard indexes without changing animal records."""
        # support default animal id sorting with a stable record tie breaker
        indexes = [
            IndexModel(
                [("animal_id", ASCENDING), ("_id", ASCENDING)],
                name="idx_animal_id_page",
            ),
            # narrow rescue candidates by animal type, sex, and age
            IndexModel(
                [
                    ("animal_type", ASCENDING),
                    ("sex_upon_outcome", ASCENDING),
                    ("age_upon_outcome_in_weeks", ASCENDING),
                ],
                name="idx_rescue_type_sex_age",
            ),
            # support ordered breed and name table views
            IndexModel(
                [("breed", ASCENDING), ("_id", ASCENDING)],
                name="idx_breed_sort",
            ),
            IndexModel(
                [("name", ASCENDING), ("_id", ASCENDING)],
                name="idx_name_sort",
            ),
        ]

        # skip equivalent indexes that already exist under another name
        existing = {
            tuple(item["key"].items()) for item in self.collection.list_indexes()
        }
        needed = [
            index for index in indexes
            if tuple(index.document["key"].items()) not in existing
        ]

        # avoid changes when all planned index patterns already exist
        if not needed:
            return []
        return self.collection.create_indexes(needed)

    # configure database-level schema checks without modifying animal records
    def ensure_schema_validation(self):
        """Install the planned validator once, without replacing existing rules."""
        from schema_validation import ANIMAL_VALIDATOR, SCHEMA_LEVEL, SCHEMA_ACTION

        # inspect collection settings before changing database metadata
        options = self.collection.options()
        existing = options.get("validator")
        if existing:
            # keep equivalent validation settings and reject unexpected rules
            if (
                existing == ANIMAL_VALIDATOR
                and options.get("validationLevel", "strict") == SCHEMA_LEVEL
                and options.get("validationAction", "error") == SCHEMA_ACTION
            ):
                return False
            raise ValueError("A different MongoDB validator is already configured.")

        # use moderate validation to protect new documents and valid updates
        self.database.command({
            "collMod": self.collection.name,
            "validator": ANIMAL_VALIDATOR,
            "validationLevel": SCHEMA_LEVEL,
            "validationAction": SCHEMA_ACTION,
        })
        return True

    # insert a new animal record into the mongodb collection
    def create(self, data):
        """Insert a document and return True if successful."""

        # check for missing input before attempting insertion
        if data is not None:
            try:
                result = self.collection.insert_one(data)
                return result.acknowledged
            # handle database errors and report unsuccessful operations
            except Exception as e:
                print("Create error:", e)

        return False

    # retrieve animal records from mongodb
    def read(self, query, projection=None):
        """Return animal records matching a MongoDB query."""

        # check for missing query
        if query is None:
            return []

        try:
            # execute query with optional projection
            cursor = self.collection.find(query, projection)

            # return matching records
            return list(cursor)

        except Exception as e:
            # handle database errors
            print("Read error:", e)
            return []

    # retrieve a sorted page of animal records from mongodb
    def read_page(
        self,
        query,
        projection=None,
        page=0,
        page_size=8,
        sort_field="animal_id",
        sort_direction=1,
    ):
        """Return one page of matching animal records."""
        # validate the query and pagination parameters
        if not isinstance(query, dict):
            raise ValueError("Query must be a dictionary.")

        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            raise ValueError("Page must be a nonnegative integer.")

        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not 1 <= page_size <= 100
        ):
            raise ValueError("Page size must be between 1 and 100.")

        # restrict sorting to approved database fields
        allowed_fields = {
            "animal_id",
            "name",
            "animal_type",
            "breed",
            "sex_upon_outcome",
            "age_upon_outcome_in_weeks",
        }

        if sort_field not in allowed_fields:
            raise ValueError("Invalid sort field.")

        if sort_direction not in (1, -1):
            raise ValueError("Invalid sort direction.")

        # calculate the offset for the requested page
        offset = page * page_size

        # sort records before applying database pagination
        cursor = (
            self.collection.find(query, projection)
            .sort([(sort_field, sort_direction), ("_id", 1)])
            .skip(offset)
            .limit(page_size)
        )

        return list(cursor)

    # group animal type or breed counts directly in mongodb
    def aggregate_field_counts(self, field, query=None, limit=None):
        """Return grouped counts without loading individual animal records."""
        # restrict field names and filter inputs used in aggregation
        if field not in ("animal_type", "breed"):
            raise ValueError("Unsupported aggregation field.")
        if query is None:
            query = {}
        if not isinstance(query, dict):
            raise ValueError("Aggregation query must be a dictionary.")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100
        ):
            raise ValueError("Aggregation limit must be between 1 and 100.")

        # count matching values and normalize empty categories
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": {"$cond": [
                    {"$in": [f"${field}", [None, ""]]}, "Unknown", f"${field}"
                ]},
                "count": {"$sum": 1},
            }},
            {"$sort": {"count": -1, "_id": 1}},
        ]
        if limit is not None:
            pipeline.append({"$limit": limit})
        return list(self.collection.aggregate(pipeline))

    # summarize age ranges in mongodb with numeric conversion
    def aggregate_age_ranges(self, query=None):
        """Count animals in age ranges using MongoDB aggregation."""
        if query is None:
            query = {}
        if not isinstance(query, dict):
            raise ValueError("Aggregation query must be a dictionary.")

        # convert missing, malformed, and numeric-string ages safely
        pipeline = [
            {"$match": query},
            {"$set": {"_age_weeks_numeric": {"$convert": {
                "input": "$age_upon_outcome_in_weeks",
                "to": "double",
                "onError": None,
                "onNull": None,
            }}}},
            {"$group": {
                "_id": {"$switch": {
                    "branches": [
                        {"case": {"$and": [
                            {"$gte": ["$_age_weeks_numeric", 0]},
                            {"$lt": ["$_age_weeks_numeric", 26]},
                        ]}, "then": "Under 26 weeks"},
                        {"case": {"$and": [
                            {"$gte": ["$_age_weeks_numeric", 26]},
                            {"$lt": ["$_age_weeks_numeric", 52]},
                        ]}, "then": "26–51 weeks"},
                        {"case": {"$and": [
                            {"$gte": ["$_age_weeks_numeric", 52]},
                            {"$lt": ["$_age_weeks_numeric", 156]},
                        ]}, "then": "52–155 weeks"},
                        {"case": {"$gte": ["$_age_weeks_numeric", 156]},
                         "then": "156+ weeks"},
                    ],
                    "default": "Unknown",
                }},
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id": 1}},
        ]
        return list(self.collection.aggregate(pipeline))

    # count animal records matching a query
    def count(self, query):
        """Return the number of matching animal records."""

        # require a valid query
        if query is None:
            raise ValueError("A query is required.")

        # count matching documents in MongoDB
        return self.collection.count_documents(query)

    # check whether an animal record exists
    def exists(self, query):
        """Return True if a matching record exists."""

        # require a nonempty query
        if not isinstance(query, dict) or not query:
            raise ValueError("A valid query is required.")

        # check for a matching document
        return self.collection.find_one(query, {"_id": 1}) is not None

    # update a single animal record by its ID
    def update(self, animal_id, new_values):
        """Update one animal record and return True if found."""

        # validate the animal ID
        if not isinstance(animal_id, str) or not animal_id.strip():
            raise ValueError("A valid Animal ID is required.")

        # validate the update data
        if not isinstance(new_values, dict) or not new_values:
            raise ValueError("Updated animal data is required.")

        # prevent changes to record identifiers and unsafe field names
        if any(
            not isinstance(field, str)
            or field.startswith("$")
            or "." in field
            or field in ("_id", "animal_id")
            for field in new_values
        ):
            raise ValueError("Invalid update fields.")

        # update only the matching animal
        result = self.collection.update_one(
            {"animal_id": animal_id.strip()},
            {"$set": new_values},
        )

        # confirm the animal was found
        return result.matched_count == 1

    # delete one animal by its unique identifier
    def delete(self, query):
        """Delete one animal identified by animal_id and return the number deleted."""

        # reject missing, empty, or unrestricted delete filters
        if not isinstance(query, dict) or set(query) != {"animal_id"}:
            raise ValueError("Deletion requires an exact animal_id filter.")

        # require a nonempty identifier rather than a query operator
        animal_id = query["animal_id"]
        if not isinstance(animal_id, str) or not animal_id.strip():
            raise ValueError("A valid animal_id is required for deletion.")

        # remove only the matching record and propagate database failures
        result = self.collection.delete_one({"animal_id": animal_id.strip()})
        return result.deleted_count
