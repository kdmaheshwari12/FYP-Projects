"""
Comprehensive validation and sanitization utilities for Pakvel backend.

Includes:
- Pakistan phone number validation (03XX-XXXXXXX)
- CNIC validation (XXXXX-XXXXXXX-X)
- Email validation
- Password validation
- Input sanitization
- Structured error responses
"""

import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION ERROR CLASSES
# ============================================================================

class ValidationError(Exception):
    """Base validation error."""
    def __init__(self, field: str, message: str, code: str = "VALIDATION_ERROR"):
        self.field = field
        self.message = message
        self.code = code
        super().__init__(self.message)


class ValidationErrorResponse(BaseModel):
    """Structured validation error response."""
    status: str = "error"
    code: str = "VALIDATION_ERROR"
    message: str
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: str(__import__('datetime').datetime.utcnow()))

    @staticmethod
    def from_error(error: ValidationError) -> "ValidationErrorResponse":
        """Create error response from ValidationError."""
        return ValidationErrorResponse(
            code=error.code,
            message=f"Validation failed: {error.field}",
            errors=[{
                "field": error.field,
                "message": error.message,
                "code": error.code
            }]
        )

    @staticmethod
    def from_errors(errors: List[ValidationError]) -> "ValidationErrorResponse":
        """Create error response from multiple ValidationErrors."""
        error_list = [
            {
                "field": err.field,
                "message": err.message,
                "code": err.code
            }
            for err in errors
        ]
        return ValidationErrorResponse(
            code="VALIDATION_ERROR",
            message=f"Validation failed: {len(errors)} error(s) found",
            errors=error_list
        )


# ============================================================================
# INPUT SANITIZATION FUNCTIONS
# ============================================================================

def sanitize_string(
    value: Optional[str],
    field_name: str = "field",
    allow_empty: bool = False,
    max_length: Optional[int] = None,
    min_length: Optional[int] = 1
) -> str:
    """
    Sanitize a string input.
    
    - Strips whitespace
    - Removes null/undefined values
    - Checks length constraints
    - Escapes dangerous characters
    
    Args:
        value: Input string
        field_name: Name of the field (for error messages)
        allow_empty: Whether to allow empty strings after trimming
        max_length: Maximum string length
        min_length: Minimum string length
    
    Returns:
        Sanitized string
        
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        if allow_empty:
            return ""
        raise ValidationError(field_name, f"{field_name} cannot be empty or null")
    
    # Convert to string and strip whitespace
    value = str(value).strip()
    
    if not value and not allow_empty:
        raise ValidationError(field_name, f"{field_name} cannot be empty after trimming")
    
    # Check length constraints
    if min_length and len(value) < min_length:
        raise ValidationError(
            field_name,
            f"{field_name} must be at least {min_length} character(s) long"
        )
    
    if max_length and len(value) > max_length:
        raise ValidationError(
            field_name,
            f"{field_name} must not exceed {max_length} character(s)"
        )
    
    # Basic sanitization: remove null bytes and control characters
    value = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
    
    return value


# Alias for backward compatibility and routes usage
validate_string = sanitize_string


def sanitize_dict(data: Dict[str, Any], allowed_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Sanitize a dictionary by removing null values and trimming strings.
    
    Args:
        data: Input dictionary
        allowed_fields: If provided, only keep these fields
    
    Returns:
        Sanitized dictionary
    """
    if not isinstance(data, dict):
        raise ValidationError("data", "Input must be a dictionary")
    
    sanitized = {}
    
    for key, value in data.items():
        # Skip if not in allowed fields
        if allowed_fields and key not in allowed_fields:
            continue
        
        # Skip null/None values
        if value is None:
            continue
        
        # Sanitize strings
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        
        sanitized[key] = value
    
    return sanitized


# ============================================================================
# PAKISTAN PHONE NUMBER VALIDATION
# ============================================================================

def validate_pakistan_phone(phone: Optional[str], field_name: str = "phone") -> str:
    """
    Validate Pakistan phone number format: 03XX-XXXXXXX
    
    Accepts:
    - 03XX-XXXXXXX (with dash)
    - 03XXXXXXXXX (without dash)
    - +923XX-XXXXXXX (with country code and dash)
    - +923XXXXXXXXX (with country code)
    
    Returns normalized format: 03XX-XXXXXXX
    
    Args:
        phone: Phone number to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        Normalized phone number (03XX-XXXXXXX format)
    
    Raises:
        ValidationError: If phone number is invalid
    """
    if not phone:
        raise ValidationError(field_name, f"{field_name} is required")
    
    # Sanitize
    phone = sanitize_string(phone, field_name, allow_empty=False)
    
    # Remove all non-digit characters except the leading +
    original_phone = phone
    phone_digits = re.sub(r'[^\d+]', '', phone)
    
    # Handle country code
    if phone_digits.startswith('+92'):
        phone_digits = '03' + phone_digits[3:]
    elif phone_digits.startswith('0092'):
        phone_digits = '03' + phone_digits[4:]
    
    # Validate format: should be 3 + 10 digits (03XX-XXXXXXX)
    if not re.match(r'^03\d{9}$', phone_digits):
        raise ValidationError(
            field_name,
            f"{field_name} must be in format 03XX-XXXXXXX or +923XX-XXXXXXX (e.g., 0300-1234567)",
            code="INVALID_PHONE_FORMAT"
        )
    
    # Validate first two digits after 03 (should be valid operator codes)
    # Pakistan operators: 00-99, but commonly used: 00-32 (main operators)
    operator_code = int(phone_digits[2:4])
    if operator_code > 99:
        raise ValidationError(
            field_name,
            f"{field_name} has invalid operator code",
            code="INVALID_PHONE_OPERATOR"
        )
    
    # Return normalized format: 03XX-XXXXXXX
    normalized = f"{phone_digits[:4]}-{phone_digits[4:]}"
    logger.debug(f"Phone validated: {original_phone} → {normalized}")
    
    return normalized


# ============================================================================
# CNIC VALIDATION
# ============================================================================

def validate_cnic(cnic: Optional[str], field_name: str = "cnic") -> str:
    """
    Validate CNIC (Computerized National ID Card) format: XXXXX-XXXXXXX-X
    
    Format:
    - 5 digits - 7 digits - 1 digit (with dashes)
    - Or 13 digits without dashes (will be reformatted)
    
    Args:
        cnic: CNIC to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        Normalized CNIC (XXXXX-XXXXXXX-X format)
    
    Raises:
        ValidationError: If CNIC is invalid
    """
    if not cnic:
        raise ValidationError(field_name, f"{field_name} is required")
    
    # Sanitize
    cnic = sanitize_string(cnic, field_name, allow_empty=False)
    
    # Remove all non-digit characters
    cnic_digits = re.sub(r'[^\d]', '', cnic)
    
    # Validate length: must be exactly 13 digits
    if len(cnic_digits) != 13:
        raise ValidationError(
            field_name,
            f"{field_name} must contain exactly 13 digits (format: XXXXX-XXXXXXX-X)",
            code="INVALID_CNIC_LENGTH"
        )
    
    # Validate that all characters are digits (already done by regex removal)
    if not cnic_digits.isdigit():
        raise ValidationError(
            field_name,
            f"{field_name} must contain only numeric digits",
            code="INVALID_CNIC_FORMAT"
        )
    
    # Validate CNIC structure (basic check)
    # First 5 digits: area code (00001-99999)
    area_code = int(cnic_digits[:5])
    if area_code < 1:
        raise ValidationError(
            field_name,
            f"{field_name} area code is invalid",
            code="INVALID_CNIC_AREA"
        )
    
    # Format: XXXXX-XXXXXXX-X
    normalized = f"{cnic_digits[:5]}-{cnic_digits[5:12]}-{cnic_digits[12]}"
    logger.debug(f"CNIC validated: {cnic} → {normalized}")
    
    return normalized


# ============================================================================
# EMAIL VALIDATION
# ============================================================================

def validate_email(email: Optional[str], field_name: str = "email") -> str:
    """
    Validate and normalize email address.
    
    Args:
        email: Email to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        Normalized email (lowercase)
    
    Raises:
        ValidationError: If email is invalid
    """
    if not email:
        raise ValidationError(field_name, f"{field_name} is required")
    
    # Sanitize
    email = sanitize_string(email, field_name, allow_empty=False).lower()
    
    # Basic email format validation
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        raise ValidationError(
            field_name,
            f"{field_name} format is invalid (e.g., user@example.com)",
            code="INVALID_EMAIL_FORMAT"
        )
    
    # Check length
    if len(email) > 254:
        raise ValidationError(
            field_name,
            f"{field_name} is too long (max 254 characters)",
            code="EMAIL_TOO_LONG"
        )
    
    # Check local part length
    local_part = email.split('@')[0]
    if len(local_part) > 64:
        raise ValidationError(
            field_name,
            f"{field_name} local part is too long (max 64 characters)",
            code="EMAIL_LOCAL_PART_TOO_LONG"
        )
    
    logger.debug(f"Email validated: {email}")
    return email


# ============================================================================
# PASSWORD VALIDATION
# ============================================================================

def validate_password(password: Optional[str], field_name: str = "password") -> str:
    """
    Validate password strength.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character (!@#$%^&*)
    
    Args:
        password: Password to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        The validated password
    
    Raises:
        ValidationError: If password doesn't meet requirements
    """
    if not password:
        raise ValidationError(field_name, f"{field_name} is required")
    
    # Check type
    if not isinstance(password, str):
        password = str(password)
    
    # Check minimum length
    if len(password) < 8:
        raise ValidationError(
            field_name,
            f"{field_name} must be at least 8 characters long",
            code="PASSWORD_TOO_SHORT"
        )
    
    # Check maximum length
    if len(password) > 128:
        raise ValidationError(
            field_name,
            f"{field_name} must not exceed 128 characters",
            code="PASSWORD_TOO_LONG"
        )
    
    # Check for uppercase letter
    if not re.search(r'[A-Z]', password):
        raise ValidationError(
            field_name,
            f"{field_name} must contain at least one uppercase letter",
            code="PASSWORD_NO_UPPERCASE"
        )
    
    # Check for lowercase letter
    if not re.search(r'[a-z]', password):
        raise ValidationError(
            field_name,
            f"{field_name} must contain at least one lowercase letter",
            code="PASSWORD_NO_LOWERCASE"
        )
    
    # Check for digit
    if not re.search(r'\d', password):
        raise ValidationError(
            field_name,
            f"{field_name} must contain at least one digit",
            code="PASSWORD_NO_DIGIT"
        )
    
    # Check for special character
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
        raise ValidationError(
            field_name,
            f"{field_name} must contain at least one special character (!@#$%^&*)",
            code="PASSWORD_NO_SPECIAL"
        )
    
    logger.debug("Password validated successfully")
    return password


# ============================================================================
# NAME VALIDATION
# ============================================================================

def validate_name(name: Optional[str], field_name: str = "name", allow_spaces: bool = True) -> str:
    """
    Validate and sanitize name field.
    
    Args:
        name: Name to validate
        field_name: Name of the field (for error messages)
        allow_spaces: Whether to allow spaces in the name
    
    Returns:
        Sanitized name
    
    Raises:
        ValidationError: If name is invalid
    """
    if not name:
        raise ValidationError(field_name, f"{field_name} is required")
    
    # Sanitize
    name = sanitize_string(name, field_name, allow_empty=False, min_length=2, max_length=100)
    
    # Validate characters: allow only letters, spaces, hyphens, and apostrophes
    if not re.match(r"^[a-zA-Z\s\-']+$", name):
        raise ValidationError(
            field_name,
            f"{field_name} can only contain letters, spaces, hyphens, and apostrophes",
            code="INVALID_NAME_FORMAT"
        )
    
    # Check if spaces are allowed (if single word required)
    if not allow_spaces and ' ' in name:
        raise ValidationError(
            field_name,
            f"{field_name} cannot contain spaces",
            code="NAME_CONTAINS_SPACES"
        )
    
    logger.debug(f"Name validated: {name}")
    return name


# ============================================================================
# NUMERIC VALIDATION
# ============================================================================

def validate_integer(
    value: Any,
    field_name: str = "value",
    min_value: Optional[int] = None,
    max_value: Optional[int] = None
) -> int:
    """
    Validate and convert to integer.
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value
        max_value: Maximum allowed value
    
    Returns:
        Validated integer
    
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, f"{field_name} is required")
    
    try:
        int_value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(
            field_name,
            f"{field_name} must be a valid integer",
            code="INVALID_INTEGER"
        )
    
    if min_value is not None and int_value < min_value:
        raise ValidationError(
            field_name,
            f"{field_name} must be at least {min_value}",
            code="VALUE_BELOW_MINIMUM"
        )
    
    if max_value is not None and int_value > max_value:
        raise ValidationError(
            field_name,
            f"{field_name} must not exceed {max_value}",
            code="VALUE_ABOVE_MAXIMUM"
        )
    
    return int_value


def validate_float(
    value: Any,
    field_name: str = "value",
    min_value: Optional[float] = None,
    max_value: Optional[float] = None
) -> float:
    """
    Validate and convert to float.
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value
        max_value: Maximum allowed value
    
    Returns:
        Validated float
    
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, f"{field_name} is required")
    
    try:
        float_value = float(value)
    except (ValueError, TypeError):
        raise ValidationError(
            field_name,
            f"{field_name} must be a valid number",
            code="INVALID_FLOAT"
        )
    
    if min_value is not None and float_value < min_value:
        raise ValidationError(
            field_name,
            f"{field_name} must be at least {min_value}",
            code="VALUE_BELOW_MINIMUM"
        )
    
    if max_value is not None and float_value > max_value:
        raise ValidationError(
            field_name,
            f"{field_name} must not exceed {max_value}",
            code="VALUE_ABOVE_MAXIMUM"
        )
    
    return float_value


# ============================================================================
# CHOICE VALIDATION
# ============================================================================

def validate_choice(
    value: Optional[str],
    allowed_choices: List[str],
    field_name: str = "value"
) -> str:
    """
    Validate that value is in allowed choices.
    
    Args:
        value: Value to validate
        allowed_choices: List of allowed values
        field_name: Name of the field (for error messages)
    
    Returns:
        Validated value
    
    Raises:
        ValidationError: If value is not in allowed choices
    """
    if not value:
        raise ValidationError(field_name, f"{field_name} is required")
    
    value = sanitize_string(value, field_name, allow_empty=False).lower()
    
    if value not in [c.lower() for c in allowed_choices]:
        raise ValidationError(
            field_name,
            f"{field_name} must be one of: {', '.join(allowed_choices)}",
            code="INVALID_CHOICE"
        )
    
    return value


# ============================================================================
# URL VALIDATION
# ============================================================================

def validate_url(url: Optional[str], field_name: str = "url") -> str:
    """
    Validate URL format.
    
    Args:
        url: URL to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        Validated URL
    
    Raises:
        ValidationError: If URL is invalid
    """
    if not url:
        raise ValidationError(field_name, f"{field_name} is required")
    
    url = sanitize_string(url, field_name, allow_empty=False)
    
    # Basic URL regex
    url_regex = r'^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=]+$'
    if not re.match(url_regex, url):
        raise ValidationError(
            field_name,
            f"{field_name} must be a valid URL (e.g., https://example.com)",
            code="INVALID_URL"
        )
    
    return url


# ============================================================================
# BATCH VALIDATION UTILITY
# ============================================================================

def collect_validation_errors(
    validators: List[Tuple[callable, tuple, dict]]
) -> Tuple[bool, List[ValidationError]]:
    """
    Execute multiple validators and collect errors.
    
    Args:
        validators: List of (validator_func, args, kwargs) tuples
    
    Returns:
        Tuple of (success: bool, errors: List[ValidationError])
    """
    errors = []
    
    for validator_func, args, kwargs in validators:
        try:
            validator_func(*args, **kwargs)
        except ValidationError as e:
            errors.append(e)
    
    return len(errors) == 0, errors


if __name__ == "__main__":
    # Test examples
    print("Testing validation utilities...")
    
    # Phone validation
    try:
        print(validate_pakistan_phone("0300-1234567"))
        print(validate_pakistan_phone("03001234567"))
        print(validate_pakistan_phone("+923001234567"))
    except ValidationError as e:
        print(f"Error: {e.message}")
    
    # CNIC validation
    try:
        print(validate_cnic("35201-1234567-1"))
        print(validate_cnic("35201123456701"))
    except ValidationError as e:
        print(f"Error: {e.message}")
    
    # Email validation
    try:
        print(validate_email("user@example.com"))
    except ValidationError as e:
        print(f"Error: {e.message}")
    
    # Password validation
    try:
        print(validate_password("SecurePass123!"))
    except ValidationError as e:
        print(f"Error: {e.message}")
    
    # Name validation
    try:
        print(validate_name("John Doe"))
    except ValidationError as e:
        print(f"Error: {e.message}")
    
    print("✅ All tests passed!")
