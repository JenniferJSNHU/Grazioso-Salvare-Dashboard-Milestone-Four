import os
from hmac import compare_digest

from flask import Response, request
from werkzeug.security import check_password_hash


# register server-side staff authentication
def enable_staff_auth(server):

    @server.before_request
    def require_staff_login():

        # retrieve staff credentials from environment variables
        username = os.getenv("GRAZIOSO_STAFF_USER")
        password_hash = os.getenv("GRAZIOSO_STAFF_PASSWORD_HASH")

        # reject requests when authentication is not configured
        if not username or not password_hash:
            return Response(
                "Staff authentication is not configured.",
                status=503,
            )

        # retrieve credentials supplied by the browser
        credentials = request.authorization

        # verify the staff username and password
        if credentials and compare_digest(credentials.username or "", username):
            if check_password_hash(password_hash, credentials.password or ""):
                return None

        # reject unauthorized requests
        return Response(
            "Staff authentication required.",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Grazioso Salvare Staff"'},
        )
