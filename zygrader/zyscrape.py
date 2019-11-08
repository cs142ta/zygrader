""" zyscrape - A wrapper around the zyBooks API """
import requests
import io
import zipfile
from datetime import datetime, timezone

from . import config

class Zyscrape:
    NO_ERROR = 0
    NO_SUBMISSION = 1
    COMPILE_ERROR = 2

    SUBMISSION_HIGHEST = "highest_score"  # Grade the most recent of the highest score

    session = None
    token = ""

    def __init__(self):
        Zyscrape.session = requests.session()

    def authenticate(self, username, password):
        auth_url = "https://zyserver.zybooks.com/v1/signin"
        payload = {"email": username, "password": password}
        
        r = Zyscrape.session.post(auth_url, json=payload)

        # Authentification failed
        if not r.json()["success"]:
            return False
        
        # Store auth token
        Zyscrape.token = r.json()["session"]["auth_token"]
        return True

    def __get_time(self, submission):
        time = submission["date_submitted"]
        date = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
        date = date.replace(tzinfo=timezone.utc).astimezone(tz=None)
        return date.strftime("%I:%M %p - %Y-%m-%d")

    def _get_score(self, submission):
        if "compile_error" in submission["results"]:
            return 0

        score = 0
        results = submission["results"]["test_results"]
        for result in results:
            score += result["score"]

        return score
    
    def _get_max_score(self, submission):
        score = 0
        tests = submission["results"]["config"]["test_bench"]
        for test in tests:
            score += test["max_score"]
        
        return score

    def get_submission(self, part_id, user_id):
        class_code = config.zygrader.CLASS_CODE
        submission_url = f"https://zyserver.zybooks.com/v1/zybook/{class_code}/programming_submission/{part_id}/user/{user_id}"
        payload = {"auth_token": Zyscrape.token}

        r = Zyscrape.session.get(submission_url, json=payload)

        return r

    def __get_submission_highest_score(self, submissions):
        highest_score = max([self._get_score(s) for s in submissions])

        for submission in reversed(submissions):
            if self._get_score(submission) is highest_score:
                return submission


    def __get_submission_most_recent(self, submissions):
        return submissions[-1]

    def download_submission(self, part_id, user_id, options):
        response = {"code": Zyscrape.NO_ERROR}

        r = self.get_submission(part_id, user_id)

        if not r.ok:
            return response

        # Get submissions
        submissions = r.json()["submissions"]

        # Student has not submitted
        if not submissions:
            response["code"] = Zyscrape.NO_SUBMISSION
            return response

        if Zyscrape.SUBMISSION_HIGHEST in options:
            submission = self.__get_submission_highest_score(submissions)
        else:
            submission = self.__get_submission_most_recent(submissions)

        # If student's code did not compile their score is 0
        if "compile_error" in submission["results"]:
            response["code"] = Zyscrape.COMPILE_ERROR

        response["score"] = self._get_score(submission)
        response["max_score"] = self._get_max_score(submission)

        response["date"] = self.__get_time(submission)
        response["zip_url"] = submission["zip_location"]

        # Success
        return response

    def download_assignment(self, user_id, assignment):
        response = {"code": Zyscrape.NO_ERROR, "name": assignment.name, "score": 0, "max_score": 0, "parts": []}
        
        has_submitted = False
        for part in assignment.parts:
            response_part = {"code": Zyscrape.NO_ERROR, "name": part["name"]}
            submission = self.download_submission(part["id"], user_id, assignment.options)

            if submission["code"] is not Zyscrape.NO_SUBMISSION:
                has_submitted = True

                response["score"] += submission["score"]
                response["max_score"] += submission["max_score"]

                response_part["score"] = submission["score"]
                response_part["max_score"] = submission["max_score"]
                response_part["zip_url"] = submission["zip_url"]
                response_part["date"] = submission["date"]

                response["parts"].append(response_part)

                if submission["code"] is Zyscrape.COMPILE_ERROR:
                    response_part["code"] = Zyscrape.COMPILE_ERROR
        
        # If student has not submitted, just return a non-success message
        if not has_submitted:
            return {"code": Zyscrape.NO_SUBMISSION}

        return response

    def extract_zip(self, input_zip):
        return {name: input_zip.read(name).decode('UTF-8') for name in input_zip.namelist()}
            
    def check_submissions(self, user_id, part, string):
        """Check each of a student's submissions for a given string"""
        submission_response = self.get_submission(part["id"], user_id)

        if not submission_response.ok:
            return {"success": False}

        all_submissions = submission_response.json()["submissions"]

        response = {"success": False}

        for submission in all_submissions:
            # Get file from zip url
            r = requests.get(submission["zip_location"], stream=True)

            try:
                z = zipfile.ZipFile(io.BytesIO(r.content))
            except zipfile.BadZipFile:
                response["error"] = f"BadZipFile Error on submission {self.__get_time(submission)}"
                continue

            f = self.extract_zip(z)

            # Check each file for the matched string
            for source_file in f.keys():
                if f[source_file].find(string) != -1:

                    # Get the date and time of the submission and return it
                    response["time"] = self.__get_time(submission)
                    response["success"] = True

                    return response
        
        return response
