"""
PAKVEL BACKEND - VALIDATION & SANITIZATION IMPLEMENTATION GUIDE

This document describes all server-side validation and sanitization implemented
across the Pakvel backend API to ensure data integrity and security.

================================================================================
1. OVERVIEW
================================================================================

All user inputs are now validated and sanitized at the server level, independent
of frontend validation. This prevents malicious input, ensures data consistency,
and provides clear error messages to clients.

Key Components:
- Core validation library: app/core/validation.py
- Input sanitization middleware: app/middleware/input_sanitization.py
- Integration in all route handlers


================================================================================
2. VALIDATION TYPES IMPLEMENTED
================================================================================

2.1 PAKISTAN PHONE NUMBER VALIDATION
────────────────────────────────────

Format: 03XX-XXXXXXX (with dash) or 03XXXXXXXXX (without dash)
Alternative: +923XX-XXXXXXX or +923XXXXXXXXX (with country code)

Function: validate_pakistan_phone(phone, field_name="phone")

Accepts:
- 0300-1234567
- 03001234567
- +923001234567
- +923001234567

Returns: Normalized format (03XX-XXXXXXX)

Validation Rules:
✓ Not null/empty
✓ Exactly 13 digits (03XXXXXXXXX)
✓ Operator code (XX after 03) is valid (00-99)
✓ Only digits and dashes allowed

Used in:
- /auth/register (phone field)
- /broker/verify (phone, optional)
- /broker/itineraries (phone, whatsapp - optional)
- /chat routes


2.2 CNIC VALIDATION
──────────────────

Format: XXXXX-XXXXXXX-X (with dashes) or 13 consecutive digits

Function: validate_cnic(cnic, field_name="cnic")

Accepts:
- 35201-1234567-1
- 35201123456701

Returns: Normalized format (XXXXX-XXXXXXX-X)

Validation Rules:
✓ Not null/empty
✓ Exactly 13 digits
✓ All characters are digits
✓ Area code (first 5 digits) is valid (00001-99999)

Used in:
- /broker/verify (CNIC - required)


2.3 EMAIL VALIDATION
─────────────────────

Format: user@example.com (standard email format)

Function: validate_email(email, field_name="email")

Returns: Normalized email (lowercase)

Validation Rules:
✓ Not null/empty
✓ Valid email format (RFC 5322 compatible)
✓ Maximum 254 characters
✓ Local part maximum 64 characters
✓ Converted to lowercase

Used in:
- /auth/register (email - required)
- /auth/login (email - required)
- /broker/verify (email - required)
- /broker/itineraries (contact_email - optional)


2.4 PASSWORD VALIDATION
──────────────────────

Function: validate_password(password, field_name="password")

Requirements:
✓ Minimum 8 characters
✓ Maximum 128 characters
✓ At least one uppercase letter (A-Z)
✓ At least one lowercase letter (a-z)
✓ At least one digit (0-9)
✓ At least one special character (!@#$%^&* etc.)

Example Valid Passwords:
- SecurePass123!
- MyTravel@2024
- PakvelApp#Admin1

Example Invalid Passwords:
- password (no uppercase, digit, special char)
- Pass123 (no special char)
- PASS123! (no lowercase)

Used in:
- /auth/register (password - required)


2.5 NAME VALIDATION
──────────────────

Function: validate_name(name, field_name="name", allow_spaces=True)

Validation Rules:
✓ Not null/empty
✓ Minimum 2 characters
✓ Maximum 100 characters
✓ Only letters, spaces, hyphens, apostrophes allowed
✓ No special characters or digits

Used in:
- /auth/register (full_name - required)
- /broker/verify (org_name - required)


2.6 STRING SANITIZATION
───────────────────────

Function: sanitize_string(value, field_name, allow_empty=False, max_length, min_length)

Features:
✓ Strips leading/trailing whitespace
✓ Removes null bytes
✓ Removes control characters
✓ Length validation
✓ Custom error messages per field

Applies to:
- Organization names
- Titles
- Descriptions
- Locations
- Taglines
- License numbers


2.7 INTEGER & FLOAT VALIDATION
───────────────────────────────

Functions:
- validate_integer(value, field_name, min_value, max_value)
- validate_float(value, field_name, min_value, max_value)

Features:
✓ Type conversion
✓ Range validation (min/max)
✓ Clear error messages

Used in:
- /broker/itineraries (duration_days, price_per_person)
- /broker/verify (years_of_experience)
- /reviews (rating)
- /trips (budget)


2.8 CHOICE VALIDATION
─────────────────────

Function: validate_choice(value, allowed_choices, field_name)

Features:
✓ Case-insensitive matching
✓ Clear error messages with allowed values

Used in:
- /trips (trip_type: "ai" or "broker")


================================================================================
3. MIDDLEWARE & GLOBAL SANITIZATION
================================================================================

3.1 INPUT SANITIZATION MIDDLEWARE
──────────────────────────────────

Location: app/middleware/input_sanitization.py
Applied to: All FastAPI middleware chain

Features:
✓ Automatically sanitizes JSON request bodies
✓ Handles nested objects and arrays
✓ Removes null bytes and control characters
✓ Trims whitespace from all string fields
✓ Prevents malicious payloads

Processes:
- POST requests with application/json
- PUT requests with application/json
- PATCH requests with application/json


3.2 REQUEST LOGGING MIDDLEWARE
──────────────────────────────

Location: app/middleware/input_sanitization.py (RequestLoggingMiddleware)

Features:
✓ Logs all incoming requests (method, path)
✓ Logs sanitized request bodies (first 500 chars)
✓ Redacts sensitive fields (password, CNIC, phone, token)
✓ Logs response status codes
✓ Debug-level logging for security audits


================================================================================
4. VALIDATION ERROR RESPONSES
================================================================================

All validation errors return structured JSON responses with HTTP 422 (Unprocessable Entity):

Format:
{
  "status": "error",
  "code": "VALIDATION_ERROR",
  "message": "Validation failed: 2 error(s) found",
  "errors": [
    {
      "field": "password",
      "message": "password must contain at least one uppercase letter",
      "code": "PASSWORD_NO_UPPERCASE"
    },
    {
      "field": "phone",
      "message": "phone must be in format 03XX-XXXXXXX or +923XX-XXXXXXX",
      "code": "INVALID_PHONE_FORMAT"
    }
  ],
  "timestamp": "2024-01-15T10:30:45.123456"
}


Error Codes:
- VALIDATION_ERROR: Generic validation failure
- INVALID_EMAIL_FORMAT: Email format invalid
- PASSWORD_TOO_SHORT: Password < 8 characters
- PASSWORD_NO_UPPERCASE: No uppercase letter
- PASSWORD_NO_LOWERCASE: No lowercase letter
- PASSWORD_NO_DIGIT: No digit
- PASSWORD_NO_SPECIAL: No special character
- INVALID_PHONE_FORMAT: Wrong phone format
- INVALID_PHONE_OPERATOR: Invalid operator code
- INVALID_CNIC_LENGTH: CNIC not 13 digits
- INVALID_CNIC_FORMAT: CNIC contains non-digits
- INVALID_NAME_FORMAT: Invalid characters in name
- INVALID_CHOICE: Value not in allowed list
- VALUE_BELOW_MINIMUM: Value too small
- VALUE_ABOVE_MAXIMUM: Value too large


================================================================================
5. ROUTE-BY-ROUTE VALIDATION MATRIX
================================================================================

5.1 AUTHENTICATION ROUTES (/auth/*)
───────────────────────────────────

POST /auth/register
{
  "email": "user@example.com",           ✓ validate_email
  "full_name": "John Doe",               ✓ validate_name
  "password": "SecurePass123!",          ✓ validate_password
  "role": "traveler"                     ✓ validate_choice (traveler|broker|admin)
}

Response 422 if validation fails
Response 400 if email already registered
Response 200 with tokens if successful


POST /auth/login
{
  "email": "user@example.com",           ✓ validate_email
  "password": "SecurePass123!"           ✓ validate_password (for format check)
}

Response 422 if email format invalid
Response 401 if credentials invalid
Response 200 with tokens if successful


5.2 BROKER ROUTES (/broker/*)
─────────────────────────────

POST /broker/verify
{
  "email": "broker@example.com",         ✓ validate_email (required)
  "org_name": "Travel Company",          ✓ validate_string, 2-100 chars
  "phone": "0300-1234567",               ✓ validate_pakistan_phone
  "cnic": "35201-1234567-1",             ✓ validate_cnic
  "license_number": "LIC123456",         ✓ validate_string, 5-50 chars
  "tagline": "Best travel experiences",  ✓ validate_string, 10-200 chars
  "years_of_experience": 5,              ✓ validate_integer, 0-70
  "specialized_areas": ["Adventure"]     ✓ non-empty list of strings
}

Response 422 if validation fails
Response 404 if user not found
Response 403 if user not a broker
Response 200 if successful


POST /broker/itineraries
{
  "title": "Hunza Adventure",            ✓ validate_string, 5-200 chars
  "departure_location": "Islamabad",     ✓ validate_string, 2-100 chars
  "arrival_location": "Hunza",           ✓ validate_string, 2-100 chars
  "description": "Amazing trip...",      ✓ validate_string, 10-5000 chars
  "duration_days": 7,                    ✓ validate_integer, 1-365
  "price_per_person": 50000,             ✓ validate_integer, 1-10000000
  "phone": "0300-1234567",               ✓ validate_pakistan_phone (optional)
  "whatsapp": "0300-1234567",            ✓ validate_pakistan_phone (optional)
  "email": "broker@example.com",         ✓ validate_email (optional)
  "trip_locations": [...],
  "days": [...]
}

Response 422 if validation fails
Response 403 if not a broker
Response 200 with itinerary ID if successful


5.3 REVIEW ROUTES (/reviews/*)
──────────────────────────────

POST /reviews/
{
  "itineraryId": "...",                  ✓ ObjectId format validation
  "rating": 5,                           ✓ validate_integer, 1-5
  "comment": "Great experience!"         ✓ validate_string, 0-5000 chars (optional)
}

Response 422 if validation fails
Response 404 if itinerary not found
Response 400 if duplicate review or unpublished itinerary
Response 403 if reviewing own itinerary
Response 200 if successful


5.4 TRIP ROUTES (/trips/*)
──────────────────────────

POST /trips/
{
  "itinerary_id": "...",                 ✓ ObjectId format validation
  "trip_type": "ai",                     ✓ validate_choice (ai|broker)
  "broker_id": "...",                    ✓ ObjectId format validation (optional)
  "destination": "Hunza",                ✓ validate_string, 2-100 chars (optional)
  "budget": 50000                        ✓ validate_integer, 1-10000000 (optional)
}

Response 422 if validation fails
Response 400 if missing required fields
Response 200 with trip ID if successful (may return existing trip)


5.5 TRAVELER ROUTES (/traveler/*)
──────────────────────────────────

POST /traveler/chat
{
  "message": "I want to visit Hunza"    ✓ validate_string, 1-5000 chars
}

Response 422 if validation fails
Response 401 if unauthorized
Response 404 if user not found
Response 200 if successful


5.6 WEATHER ROUTES (/weather/*)
────────────────────────────────

GET /weather/live?city=Islamabad
  city: "Islamabad"                      ✓ validate_string, 2-100 chars

Response 422 if validation fails
Response 400 if city not found
Response 200 with weather data if successful


================================================================================
6. SECURITY CONSIDERATIONS
================================================================================

6.1 Defense in Depth
────────────────────
- Server-side validation independent of frontend
- Cannot be bypassed by clever HTTP clients
- Malformed requests rejected early
- Database cannot receive invalid data


6.2 Sensitive Data Handling
───────────────────────────
- CNIC numbers never logged
- Phone numbers never logged in cleartext
- Passwords never logged
- Tokens never logged
- Only redacted in debug logs


6.3 Input Injection Prevention
──────────────────────────────
- Null bytes removed
- Control characters sanitized
- Whitespace trimmed
- No eval() or dynamic code execution
- Type validation (int, string, etc.)


6.4 Rate Limiting & DOS Prevention
───────────────────────────────────
- Maximum string lengths enforced
- Maximum array sizes validated
- Large payloads rejected at middleware level
- JSON size limits inherited from FastAPI defaults


================================================================================
7. TESTING & VALIDATION
================================================================================

7.1 Test Cases to Run
─────────────────────

Phone Validation:
✓ curl -X POST http://localhost:8000/broker/verify -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","org_name":"Test","phone":"0300-1234567","cnic":"35201-1234567-1"}'

✗ curl -X POST http://localhost:8000/broker/verify \
  -d '{"phone":"invalid-phone"}'  → Should return 422 error

CNIC Validation:
✓ validate_cnic("35201-1234567-1") → "35201-1234567-1"
✗ validate_cnic("123-456") → ValidationError
✗ validate_cnic("352011234567") → ValidationError (12 digits, need 13)

Email Validation:
✓ validate_email("user@example.com") → "user@example.com"
✗ validate_email("invalid-email") → ValidationError
✗ validate_email("user@") → ValidationError

Password Validation:
✓ validate_password("SecurePass123!") → "SecurePass123!"
✗ validate_password("weak") → ValidationError
✗ validate_password("NoDigits!") → ValidationError
✗ validate_password("nouppercaseL1!") → ValidationError

Name Validation:
✓ validate_name("John Doe") → "John Doe"
✗ validate_name("John123") → ValidationError (contains digits)
✗ validate_name("J") → ValidationError (too short)


7.2 Integration Testing
──────────────────────

Test Auth Registration:
POST /auth/register
{
  "email": "newuser@example.com",
  "full_name": "Ahmed Khan",
  "password": "MyPassword123!",
  "role": "traveler"
}

Expected: 200 with access_token, refresh_token

Test Invalid Email:
POST /auth/register
{
  "email": "invalid@",
  "full_name": "Ahmed Khan",
  "password": "MyPassword123!"
}

Expected: 422 with validation error

Test Weak Password:
POST /auth/register
{
  "email": "user@example.com",
  "full_name": "Ahmed Khan",
  "password": "weak"
}

Expected: 422 with PASSWORD_TOO_SHORT error


7.3 Middleware Testing
──────────────────────

Verify Input Sanitization:
POST /traveler/chat
{
  "message": "  Hello world  "  (with extra spaces)
}

Expected: Message stored as "Hello world" (trimmed)


Verify Control Character Removal:
POST /traveler/chat
{
  "message": "Hello\x00World"  (with null byte)
}

Expected: Message stored as "HelloWorld" (null byte removed)


================================================================================
8. MAINTENANCE & UPDATES
================================================================================

8.1 Adding New Validators
─────────────────────────

To create a new validator:

1. Add function to app/core/validation.py:

   def validate_custom_field(value, field_name="field"):
       if not value:
           raise ValidationError(field_name, f"{field_name} is required")
       
       # Perform validation
       if not is_valid(value):
           raise ValidationError(
               field_name, 
               f"{field_name} format is invalid",
               code="INVALID_CUSTOM_FORMAT"
           )
       
       return value

2. Use in route:

   from app.core.validation import validate_custom_field
   
   try:
       validated = validate_custom_field(data.get("field"))
   except ValidationError as e:
       errors.append(e)


8.2 Updating Validation Rules
────────────────────────────

To change a validation rule (e.g., password length):

1. Edit the validator function in app/core/validation.py
2. Update test cases
3. Document changes here
4. Test affected endpoints


8.3 Logging & Monitoring
────────────────────────

All validation failures are logged:
- ERROR level: Security incidents (injection attempts, etc.)
- WARNING level: Validation failures (user error)
- DEBUG level: Request/response details


Check logs for patterns:
- Multiple validation failures from same IP
- Unusual input patterns
- Repeated attempts with malformed data


================================================================================
9. BACKWARD COMPATIBILITY
================================================================================

All changes maintain backward compatibility:
✓ Existing valid requests still work
✓ Response formats unchanged
✓ Database schemas unchanged
✓ Frontend no changes required

Note: Frontend validation should remain in place as first-line defense
for better UX, but backend validation is now independent and comprehensive.


================================================================================
10. QUICK REFERENCE
================================================================================

Common Validations:

Email:           validate_email(email)
Password:        validate_password(password)  
Phone (PK):      validate_pakistan_phone(phone)
CNIC:            validate_cnic(cnic)
Name:            validate_name(name)
Text:            validate_string(text, field_name)
Integer:         validate_integer(value, field_name, min, max)
Choice:          validate_choice(value, allowed_list, field_name)

All raise ValidationError on failure
All include detailed error messages
All have error codes for programmatic handling

================================================================================
"""
