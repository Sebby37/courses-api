import re
from datetime import datetime
from typing import Union

from fastapi import FastAPI

from .data_fetcher import DataFetcher

def current_year() -> str:
    """Gets the current year, needed explicitly for the COURSE_DTL CoursePlanner API endpoint as other years break the response"""
    return datetime.now().year

def current_sem() -> str:
    """Gets the current semester, to be used as a simple default for /courses/  """
    return "Semester 1" if datetime.now().month <= 6 else "Semester 2" # Not the most bulletproof logic lol

def meeting_date_convert(raw_date: str) -> dict[str]:
    """Converts the date format given in the meetings to "MM-DD"

    Args:
        raw_date (str): The given meeting date in the format of "DD {3-char weekday} - DD {3-char weekday}"

    Returns:
        formatted_date (dict[str]): The formatted meeting date in the format of "MM-DD" in a dict containing 
        the "start" and "end" keys and their corresponding dates
    """
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    start, end = raw_date.split(" - ")
    
    start_d, start_m = start.split()
    start_m = str(months.index(start_m) + 1).zfill(2)
    
    end_d, end_m = end.split()
    end_m = str(months.index(end_m) + 1).zfill(2)
    
    formatted_date = {
        "start": f"{start_m}-{start_d.zfill(2)}",
        "end": f"{end_m}-{end_d.zfill(2)}"
    }
    return formatted_date

def meeting_time_convert(raw_time: str) -> str:
    """Converts the time given in meetings to "HH:mm"

    Args:
        raw_time (str): The given meeting time in the format of "H{am/pm}"

    Returns:
        formatted_time (str): The formatted meeting time in the format of "HH:mm"
    """
    
    period = raw_time[-2:]
    hour = int(raw_time.replace(period, ""))
    
    if period.lower() == "pm":
        hour += 12
    
    hour = str(hour).zfill(2)
    formatted_time = f"{hour}:00"
    return formatted_time

def parse_requisites(raw_requisites: str) -> Union[dict[str], None]:
    """Takes in a string of -requisites and returns a dict containing the original string, and a list of the parsed-out subjects

    Args:
        raw_requisites (str): The raw string containing a list of -requisites, usually in the format of 
        "COMP SCI 1103, COMP SCI 2202, COMP SCI 2202B" as an example

    Returns:
        parsed_requisites (Union[dict[str], None]): Either a dict with "desc"s value being the original -requisites string and 
        "subjects" being a list of the parsed -requisites, or None if raw_requisites is None
    """
    
    if not raw_requisites:
        return None
    
    # Note: This regex pattern was generated by Claude 3.5 Sonnet, works fine in my testing though
    pattern = r'\b([A-Z]+(?:\s+[A-Z]+)*)\s+(\d{4}\w*)\b'
    matched_subjects = [" ".join(match) for match in re.findall(pattern, raw_requisites)]
    
    parsed_requisites = None
    if len(matched_subjects) > 0:
        parsed_requisites = {
            "desc": raw_requisites,
            "subjects": matched_subjects
        }
    
    return parsed_requisites

def convert_term_alias(term_alias: str) -> str:
    """Takes in a term alias and returns the CoursePlanner API name for said term

    Args:
        term_alias (str): The unconverted term, this doesn't have to be an alias in which case no conversion will be done

    Returns:
        str: The converted or original term depending on if a conversion was made
    """
    
    terms_without_digits = ("fast", "summer", "winter")
    aliases = {
        "sem": "Semester",
        "elc": "ELC Term",
        "tri": "Trimester",
        "term": "Term",
        "ol": "Online Teaching Period",
        "melb": "Melb Teaching Period",
        "fast": "Fast Track",
        "pce": "PCE Term",
        "summer": "Summer School",
        "winter": "Winter School"
    }
    
    # Convert the alias, append it's digit to the end if the term needs a digit at the end
    converted_alias = aliases.get(term_alias[:-1] if term_alias[-1].isdigit() else term_alias, term_alias)
    if term_alias not in terms_without_digits and term_alias[-1].isdigit() and converted_alias != term_alias:
        converted_alias += " " + term_alias[-1]
    
    return converted_alias

def get_term_number(year: int, term: str) -> int:
    """Converts a year and term string to the courseplanner term number

    Args:
        year (int): The term's year
        term (str): The term as a full string, for example "Semester 1" or "Semester 2", or as one of "sem1" or "sem2"

    Raises:
        Exception: Throws an exception on an invalid term

    Returns:
        int: The term number used in the CoursePlanner API
    """
    
    # Convert aliases
    year = str(year)
    term = convert_term_alias(term)
    
    terms_raw = DataFetcher(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/TERMS/queryx&virtual=Y&year_from=0&year_to=9999").get()["data"]
    
    # Find and return the chosen term number
    for cur_term in terms_raw:
        if year + " " + term == cur_term["DESCR"]:
            return cur_term["TERM"]
        
    # Syntax error on invalid term
    raise Exception(f"Invalid term: {term}")


def get_course_info(course_id: int, year: int, term: str) -> dict:
    """Gets the course info given an ID, year and term, and returns a dict as described in the spec

    Args:
        course_id (int): The ID of the course as used in the CoursePlanner API
        year (int): The year the course takes place in
        term (str): The term the course takes place in, either as "sem1", "sem2", "Semester 1", "Semester 2", or the ID of that term

    Returns:
        dict: A dict containing the course info per the spec, see issue #3 for more info
    """
    
    course_info = dict()
    
    term_number = get_term_number(year, term)
    details = DataFetcher(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_DTL/queryx&virtual=Y&year={year}&courseid={course_id}&term={term_number}").get()["data"][0]
    classes = DataFetcher(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_CLASS_LIST/queryx&virtual=Y&crseid={course_id}&term={term_number}&offer=1&session=1").get()["data"][0]
    
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
        "course_id": course_id,
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
    """Takes in a year and term, and returns a list of all courses in that year and term as dicts described in the spec

    Args:
        year (int): The year of the courses from 2006 to the current year
        term (str): The term as either an ID or a string

    Raises:
        Exception: Raises exception on an invalid year

    Returns:
        list[dict]: A list of courses as dicts described in the spec in issue #3
    """
    
    # Make sure year is within bounds
    if year < 2006 or year > current_year():
        raise Exception(f"Invalid year: {year}")
    
    MAX_RESULTS = 5000
    term_url = "&term=" + get_term_number(year, term) if term is not None else ""
    courses_raw = DataFetcher(f"https://courseplanner-api.adelaide.edu.au/api/course-planner-query/v1/?target=/system/COURSE_SEARCH/queryx&virtual=Y&year={year}&pagenbr=1&pagesize={MAX_RESULTS}" + term_url).get()["data"]
    
    courses = []
    for course in courses_raw:
        courses.append({
            "course_id": course["COURSE_ID"],
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

@app.get("/course/{course_id}")
async def course_info_route(course_id, year: int = None, term: str = None):
    """Course details route, takes in a course ID (and optionally a year and term) and returns the courses' info and classes

    Args:
        course_id: The ID of the course
        year (int, optional): The year the course takes place in. Defaults to None.
        term (str, optional): The term the course takes place in. Defaults to None.

    Returns:
        dict: A dictionary containing the course information and classes
    """
    
    course_id = int(course_id)
    
    if year is None:
        year = current_year()
    if term is None:
        term = current_sem()
    
    return get_course_info(course_id, year, term)

@app.get("/courses/")
async def courses_route(year: int = None, term: str = None):
    """Gets a list of courses given (optionally) the year and term

    Args:
        year (int, optional): The year of the courses from 2006 to the current year. Defaults to None.
        term (str, optional): The term of the courses. Defaults to None.

    Returns:
        list[dict]: A list of courses as dictionaries
    """
    
    # Default args
    if year is None:
        year = current_year()
    
    return get_courses(year, term)
