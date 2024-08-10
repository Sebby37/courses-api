import re
import requests
from datetime import datetime
from fastapi import FastAPI

# Gets the current year, needed explicitly for the COURSE_DTL CoursePlanner API endpoint as other years break the response
def current_year() -> str:
    return datetime.now().year

# Gets the current semester, to be used as a simple default for /courses/
def current_sem() -> str:
    return "Semester 1" if datetime.now().month <= 6 else "Semester 2" # Not the most bulletproof logic lol

# Converts the date format given in the meetings to "MM-DD"
def meeting_date_convert(raw_date: str) -> dict[str]:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    start, end = raw_date.split(" - ")
    
    start_d, start_m = start.split(" ")
    start_m = str(months.index(start_m) + 1).zfill(2)
    
    end_d, end_m = end.split(" ")
    end_m = str(months.index(end_m) + 1).zfill(2)
    
    return {
        "start": f"{start_m}-{start_d.zfill(2)}",
        "end": f"{end_m}-{end_d.zfill(2)}"
    }

# Converts the time given in meetings to "HH:mm"
def meeting_time_convert(raw_time: str) -> str:
    period = raw_time[-2:]
    hour = int(raw_time.replace(period, ""))
    
    if period.lower() == "pm":
        hour += 12
    
    hour = str(hour).zfill(2)
    return f"{hour}:00"

# Takes in a string of -requisites and returns a dict containing the original string, and a list of the parsed-out subjects
def parse_requisites(raw_requisites):
    if not raw_requisites:
        return None
    
    # Note: This regex pattern was generated by Claude 3.5 Sonnet, works fine in my testing though
    pattern = r'\b([A-Z]+(?:\s+[A-Z]+)*)\s+(\d{4}\w*)\b'
    matched_subjects = [" ".join(match) for match in re.findall(pattern, raw_requisites)]
    
    if len(matched_subjects) > 0:
        return {
            "desc": raw_requisites,
            "subjects": matched_subjects
        }
    else:
        return raw_requisites

# Converts a year and term string to the courseplanner term number
def get_term_number(year: int, term: str) -> int:
    # Make sure year and term are of the correct format
    year = str(year)
    term = {
        "sem1": "Semester 1",
        "sem2": "Semester 2"
    }.get(term, term)
    
    terms_raw = requests.get(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/TERMS/queryx&virtual=Y&year_from=0&year_to=9999").json()["data"]["query"]["rows"]
    
    # Find and return the chosen term number
    for cur_term in terms_raw:
        if year + " " + term == cur_term["DESCR"]:
            return cur_term["TERM"]
        
    # Syntax error on invalid term
    raise SyntaxError(f"Invalid term: {term}")


def get_course_info(id: int, year: int, term: str) -> dict:
    course_info = dict()
    
    term_number = get_term_number(year, term)
    details = requests.get(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_DTL/queryx&virtual=Y&year={year}&courseid={id}&term={term_number}").json()["data"]["query"]["rows"][0]
    classes = requests.get(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_CLASS_LIST/queryx&virtual=Y&crseid={id}&term={term_number}&offer=1&session=1").json()["data"]["query"]["rows"][0]
    
    # Format the classes properly
    classes_formatted = []
    for class_detail in classes["groups"]:
        cur_class_details = {
            "type": class_detail["type"],
            "classes": []
        }
        
        classes = []
        for _class in class_detail["classes"]:
            cur_class = {
                "number": _class["class_nbr"],
                "section": _class["section"],
                "capacity": { # Not in the spec, but useful to have
                    "size": _class["size"],
                    "enrolled": _class["enrolled"],
                    "available": _class["available"] if _class["available"] != "FULL" else 0,
                },
                "notes": _class["notes"] if "notes" in _class.keys() else [], # Leaving this as it is in the API
                "meetings": []
            }
            
            meetings = []
            for meeting in _class["meetings"]:
                meetings.append({
                    "day": meeting["days"],
                    "date": meeting_date_convert(meeting["dates"]),
                    "time": {
                        "start": meeting_time_convert(meeting["start_time"]),
                        "end": meeting_time_convert(meeting["end_time"])
                    },
                    "location": meeting["location"]
                })
            
            cur_class["meetings"] = meetings
            classes.append(cur_class)
            
        cur_class_details["classes"] = classes
        classes_formatted.append(cur_class_details)
    
    course_info = {
        "id": id,
        "name": {
            "subject": details["SUBJECT"],
            "code": details["CATALOG_NBR"],
            "title": details["COURSE_TITLE"]
            # Below removed because such info is not in the courseplanner api
            #"other_names": ["ADDS", "DSA", "Data structures and algorithms"], # case insensitive in frontend search
        },
        "class_number": details["CLASS_NBR"],
        "year": details["YEAR"],
        "term": details["TERM_DESCR"], # Could use the "TERM" field but would then need to match the given term code
        "campus": details["CAMPUS"],
        "career": details["ACAD_CAREER_DESCR"], # Using a full text version instead of a code (eg UGRD)
        "units": details["UNITS"],
        "requirement": {
            "restriction": details["RESTRICTION_TXT"] if details["RESTRICTION"] == "Y" else None,
            # Requisites are parsed into a dict with the original string and parsed subjects
            "prerequisite": parse_requisites(details["PRE_REQUISITE"]),
            "corequisite": parse_requisites(details["CO_REQUISITE"]),
            "assumed_knowledge": parse_requisites(details["ASSUMED_KNOWLEDGE"]),
            "incompatible": parse_requisites(details["INCOMPATIBLE"])
        },
        # Not in the spec
        "description": details["SYLLABUS"],
        "assessment": details["ASSESSMENT"],
        "contact": details["CONTACT"], # Could parse to a float of hours, takes the format of "Up to [hours] hours per week"
        "critical_dates": { # These come in the format of "[3-char weekday] DD/MM/YYYY"
            "last_day_add_online": details["CRITICAL_DATES"]["LAST_DAY"],
            "census_date": details["CRITICAL_DATES"]["CENSUS_DT"],
            "last_day_wnf": details["CRITICAL_DATES"]["LAST_DAY_TO_WFN"],
            "last_day_wf": details["CRITICAL_DATES"]["LAST_DAY_TO_WF"]
        },
        "outline_url": details["URL"],
        "class_list": classes_formatted
    }
    
    return course_info

def get_courses(year: int, term: str) -> list[dict]:
    # Make sure year is within bounds
    if year < 2006 or year > current_year():
        raise SyntaxError(f"Invalid year: {year}")
    
    MAX_RESULTS = 5000
    term_url = "&term=" + get_term_number(year, term) if term != None else ""
    courses_raw = requests.get(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_SEARCH/queryx&virtual=Y&year={year}&pagenbr=1&pagesize={MAX_RESULTS}" + term_url).json()["data"]["query"]["rows"]
    
    courses = []
    for course in courses_raw:
        courses.append({
            "id": course["COURSE_ID"],
            "name": course["SUBJECT"] + " " + course["CATALOG_NBR"],
            # Below info was not specified, but I feel it could be useful
            "title": course["COURSE_TITLE"],
            "subject": course["SUBJECT"],
            "number": course["CATALOG_NBR"],
            "career": course["ACAD_CAREER_DESCR"], # Could use the code instead (ex: UGRD instead of Undergraduate)
            "year": course["YEAR"],
            "term": term,
            "units": course["UNITS"],
            "campus": course["CAMPUS"]
        })
    
    return courses

''' FastAPI stuff below '''
app = FastAPI()

# Course details, takes in just a course ID and returns all course info and it's class times and such
# Also optionally takes in a year and semester as query params, but both default to the current ones
@app.get("/course/{id}")
async def course_info_route(id, year: int = None, term: str = None):
    id = int(id)
    
    if year == None:
        year = current_year()
    if term == None:
        term = current_sem()
    
    return get_course_info(id, year, term)

# List of courses given (year, term)
@app.get("/courses/")
async def courses_route(year: int = None, term: str = None):
    # Default args
    if year == None:
        year = current_year()
    
    return get_courses(year, term)
