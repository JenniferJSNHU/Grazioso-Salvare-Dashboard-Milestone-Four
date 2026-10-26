import heapq
import math
import re

from animal_service import RESCUE_QUERIES

# assign up to six breed points based on project-defined rescue preferences
# these scores are illustrative and do not measure an individual dog's training
BREED_SCORES = {
    "water": {
        "Newfoundland": 6,
        "Labrador Retriever": 5,
        "Chesapeake Bay Retriever": 4,
    },
    "mountain": {
        "German Shepherd": 6,
        "Siberian Husky": 5,
        "Alaskan Malamute": 5,
        "Rottweiler": 4,
        "Old English Sheepdog": 3,
    },
    "disaster": {
        "Bloodhound": 6,
        "German Shepherd": 6,
        "Golden Retriever": 5,
        "Doberman Pinscher": 4,
        "Rottweiler": 4,
    },
}


# define preferred age ranges in weeks for each rescue assignment
PREFERRED_AGE_RANGES = {
    "water": (52, 104),
    "mountain": (52, 104),
    "disaster": (52, 156),
}


# confirm the requested rescue category is supported
# use one validation rule for scoring and both ranking methods
def validate_category(category):
    if category not in RESCUE_QUERIES or category not in BREED_SCORES:
        raise ValueError("Unknown rescue category.")


# confirm the requested number of candidates is a positive integer
def validate_limit(k):
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer.")


# check the original rescue eligibility requirements before ranking
def is_eligible(animal, category):
    validate_category(category)

    # skip malformed or incomplete records
    if not isinstance(animal, dict):
        return False

    criteria = RESCUE_QUERIES[category]
    breed = animal.get("breed")
    age = animal.get("age_upon_outcome_in_weeks")

    # require the animal type and sex specified by the original rescue filter
    if animal.get("animal_type") != criteria["animal_type"]:
        return False
    if animal.get("sex_upon_outcome") != criteria["sex_upon_outcome"]:
        return False

    # require a breed matching the original rescue filter
    if not isinstance(breed, str) or not breed.strip():
        return False
    if not re.search(criteria["breed"]["$regex"], breed, re.IGNORECASE):
        return False

    # reject missing, boolean, nonnumeric, and nonfinite ages
    if isinstance(age, bool) or not isinstance(age, (int, float)):
        return False
    if not math.isfinite(age):
        return False

    # retain the original minimum and maximum eligible ages
    age_range = criteria["age_upon_outcome_in_weeks"]
    return age_range["$gte"] <= age <= age_range["$lte"]


# award breed points for a recognized breed in the selected rescue category
def breed_score(animal, category):
    breed = animal["breed"]

    # prefer the longest matching breed name when a record contains mixed breeds
    matches = [
        (len(name), points)
        for name, points in BREED_SCORES[category].items()
        if name.casefold() in breed.casefold()
    ]
    return max(matches)[1] if matches else 0


# award one to four age points using the preferred and eligible age ranges
def age_score(animal, category):
    age = animal["age_upon_outcome_in_weeks"]
    preferred_min, preferred_max = PREFERRED_AGE_RANGES[category]
    eligible_range = RESCUE_QUERIES[category]["age_upon_outcome_in_weeks"]

    # award four points to ages within the central half of the preferred range
    midpoint = (preferred_min + preferred_max) / 2
    central_half_width = (preferred_max - preferred_min) / 4
    if abs(age - midpoint) <= central_half_width:
        return 4

    # award three points to other ages inside the preferred range
    if preferred_min <= age <= preferred_max:
        return 3

    # award two points when just outside the preferred range
    # award one point when closer to the outer eligibility boundary
    if age < preferred_min:
        outside_distance = preferred_min - age
        available_distance = preferred_min - eligible_range["$gte"]
    else:
        outside_distance = age - preferred_max
        available_distance = eligible_range["$lte"] - preferred_max

    return 2 if outside_distance <= available_distance / 2 else 1


# calculate a score out of ten for an eligible rescue candidate
def calculate_score(animal, category):
    validate_category(category)

    # return zero for animals that fail the original rescue requirements
    if not is_eligible(animal, category):
        return 0

    # combine breed points (up to six) and age points (up to four)
    return breed_score(animal, category) + age_score(animal, category)


# select the top k candidates without sorting the full eligible dataset
def rank_candidates(animals, category, k=10):
    validate_category(category)
    validate_limit(k)

    # keep only the k strongest candidates in a min-heap
    heap = []

    # preserve input order as the tie-breaker for equal scores
    for index, animal in enumerate(animals):
        if not is_eligible(animal, category):
            continue

        score = calculate_score(animal, category)
        entry = (score, -index, animal)

        # fill the heap before replacing lower-ranked candidates
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry[:2] > heap[0][:2]:
            heapq.heapreplace(heap, entry)

    # sort only the selected candidates into descending rank order
    return [
        {"animal": animal, "score": score}
        for score, _, animal in sorted(heap, reverse=True)
    ]


# sort all eligible candidates as a benchmark comparison for the min-heap
def rank_candidates_sorted(animals, category, k=10):
    validate_category(category)
    validate_limit(k)

    ranked = []

    # evaluate candidates with the same eligibility and scoring functions
    for index, animal in enumerate(animals):
        if not is_eligible(animal, category):
            continue

        score = calculate_score(animal, category)
        ranked.append((score, -index, animal))

    # sort the full candidate list, preserving input order for tied scores
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)

    # return the same result structure used by the min-heap algorithm
    return [{"animal": animal, "score": score} for score, _, animal in ranked[:k]]
