#!/usr/bin/env python3
"""
VLM Response Format Enforcement
Robust parsing and validation of VLM outputs with structured schemas
"""

import json
import re
import logging
from typing import Type, TypeVar, Optional, Dict, Any, List
from pydantic import BaseModel, ValidationError, Field

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


# ===== Response Models =====

class ValidationResult(BaseModel):
    """VLM validation response schema"""
    format_issues: List[str] = Field(
        default_factory=list,
        description="List of formatting issues found"
    )
    missing_content: List[str] = Field(
        default_factory=list,
        description="List of missing content items"
    )
    improvement_suggestions: List[str] = Field(
        default_factory=list,
        description="List of improvement suggestions"
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1"
    )


class ImageDescription(BaseModel):
    """Image description response schema"""
    title: str = Field(..., description="Title or caption of the image")
    description: str = Field(..., description="Detailed description of image content")
    page_number: Optional[int] = Field(None, description="Source page number")
    figure_number: Optional[str] = Field(None, description="Figure number if labeled")


class TableAnalysis(BaseModel):
    """Table analysis response schema"""
    table_title: str = Field(..., description="Title of the table")
    column_headers: List[str] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list, description="Key facts extracted as bullets")
    row_count: Optional[int] = Field(None, description="Number of data rows")


# ===== JSON Extraction Functions =====

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from text that may contain additional content
    
    Tries multiple strategies:
    1. Direct JSON parse
    2. Extract JSON block with regex
    3. Find first {...} or [...]
    4. Extract from markdown code blocks
    
    Args:
        text: Text potentially containing JSON
        
    Returns:
        Parsed JSON dict or None
    """
    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Extract from markdown code block
    code_block_pattern = r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```'
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Strategy 3: Find JSON object or array
    json_patterns = [
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Nested objects
        r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]',  # Nested arrays
    ]
    
    for pattern in json_patterns:
        matches = re.finditer(pattern, text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    
    return None


def lax_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """
    More permissive JSON parsing with cleanup
    
    Handles:
    - Single quotes instead of double quotes
    - Trailing commas
    - Unquoted keys
    - Comments
    
    Args:
        text: JSON-like text
        
    Returns:
        Parsed dict or None
    """
    try:
        # Remove comments
        text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        
        # Replace single quotes with double quotes (careful with apostrophes)
        text = re.sub(r"(?<!\\)'", '"', text)
        
        # Remove trailing commas
        text = re.sub(r',\s*}', '}', text)
        text = re.sub(r',\s*]', ']', text)
        
        return json.loads(text)
    except (json.JSONDecodeError, Exception):
        return None


# ===== Structured Parsing =====

def parse_vlm_response(
    response: str,
    schema: Type[T],
    fallback: Optional[T] = None,
    verbose: bool = False
) -> T:
    """
    Parse and validate VLM response against Pydantic schema
    
    Tries multiple parsing strategies with progressive fallback:
    1. Direct schema validation
    2. Extract JSON from text, then validate
    3. Lax JSON parsing, then validate
    4. Return fallback if provided
    5. Raise error
    
    Args:
        response: VLM text response
        schema: Pydantic model class to validate against
        fallback: Optional fallback instance to return on failure
        verbose: Enable detailed logging
        
    Returns:
        Validated Pydantic model instance
        
    Raises:
        ValueError: If parsing fails and no fallback provided
    """
    if verbose:
        logger.info(f"📋 Parsing VLM response with schema: {schema.__name__}")
        logger.debug(f"Response preview: {response[:200]}...")
    
    # Parsing strategies
    strategies = [
        ("direct_json", lambda: schema(**json.loads(response))),
        ("extract_json", lambda: schema(**extract_json_from_text(response))),
        ("lax_json", lambda: schema(**lax_json_parse(response))),
    ]
    
    # Try each strategy
    for strategy_name, strategy_fn in strategies:
        try:
            if verbose:
                logger.info(f"  🔍 Trying strategy: {strategy_name}")
            
            result = strategy_fn()
            
            if result is not None:
                if verbose:
                    logger.info(f"  ✅ Success with {strategy_name}")
                return result
        except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as e:
            if verbose:
                logger.debug(f"  ❌ {strategy_name} failed: {str(e)[:100]}")
            continue
        except Exception as e:
            if verbose:
                logger.warning(f"  ⚠️  {strategy_name} unexpected error: {str(e)[:100]}")
            continue
    
    # All strategies failed
    if fallback is not None:
        logger.warning(f"⚠️  All parsing strategies failed. Using fallback for {schema.__name__}")
        if verbose:
            logger.debug(f"Failed response:\n{response[:500]}")
        return fallback
    
    # No fallback - raise error
    error_msg = f"Could not parse VLM response into {schema.__name__}"
    logger.error(f"❌ {error_msg}")
    logger.debug(f"Response:\n{response[:1000]}")
    raise ValueError(f"{error_msg}\n\nResponse preview:\n{response[:500]}")


def enforce_json_schema(prompt: str, schema: Dict[str, Any]) -> str:
    """
    Append JSON schema instructions to prompt
    
    Args:
        prompt: Original prompt
        schema: JSON schema dictionary
        
    Returns:
        Enhanced prompt with schema instructions
    """
    schema_instruction = f"""

IMPORTANT: You MUST respond with ONLY valid JSON matching this exact schema:

```json
{json.dumps(schema, indent=2)}
```

Requirements:
- Do not include any text before or after the JSON
- Ensure all quotes are properly escaped
- Use double quotes for strings, not single quotes
- No trailing commas
- All required fields must be present
- Follow the exact field names and types specified
"""
    
    return prompt + schema_instruction


def enforce_pydantic_schema(prompt: str, model: Type[BaseModel]) -> str:
    """
    Append Pydantic model schema instructions to prompt
    
    Args:
        prompt: Original prompt
        model: Pydantic model class
        
    Returns:
        Enhanced prompt with schema instructions
    """
    schema = model.schema()
    return enforce_json_schema(prompt, schema)


# ===== Batch Parsing =====

def parse_multiple_responses(
    responses: List[str],
    schema: Type[T],
    fallback: Optional[T] = None,
    verbose: bool = False
) -> List[T]:
    """
    Parse multiple VLM responses
    
    Args:
        responses: List of VLM text responses
        schema: Pydantic model class
        fallback: Optional fallback for failed parses
        verbose: Enable detailed logging
        
    Returns:
        List of validated instances
    """
    results = []
    failed_count = 0
    
    for i, response in enumerate(responses):
        try:
            result = parse_vlm_response(response, schema, fallback=fallback, verbose=verbose)
            results.append(result)
        except ValueError as e:
            failed_count += 1
            logger.error(f"Failed to parse response {i+1}/{len(responses)}: {e}")
            if fallback is not None:
                results.append(fallback)
    
    if failed_count > 0:
        logger.warning(f"⚠️  {failed_count}/{len(responses)} responses failed to parse")
    
    return results


# ===== Validation Helpers =====

def validate_response_completeness(
    response_dict: Dict[str, Any],
    required_fields: List[str]
) -> bool:
    """
    Check if response contains all required fields
    
    Args:
        response_dict: Parsed response dictionary
        required_fields: List of required field names
        
    Returns:
        True if all fields present and non-empty
    """
    for field in required_fields:
        if field not in response_dict:
            logger.warning(f"Missing required field: {field}")
            return False
        
        value = response_dict[field]
        if value is None or (isinstance(value, (list, str)) and len(value) == 0):
            logger.warning(f"Empty required field: {field}")
            return False
    
    return True


def create_fallback_response(
    schema: Type[T],
    error_message: str = "Failed to parse VLM response"
) -> T:
    """
    Create a safe fallback response for a schema
    
    Args:
        schema: Pydantic model class
        error_message: Error message to include
        
    Returns:
        Fallback instance with safe default values
    """
    # Create instance with defaults
    try:
        return schema()
    except ValidationError:
        # If defaults don't work, construct minimal valid instance
        if schema == ValidationResult:
            return ValidationResult(
                format_issues=[error_message],
                missing_content=[],
                improvement_suggestions=[],
                confidence=0.0
            )
        elif schema == ImageDescription:
            return ImageDescription(
                title="Unknown",
                description=error_message
            )
        elif schema == TableAnalysis:
            return TableAnalysis(
                table_title="Unknown",
                column_headers=[],
                key_facts=[error_message]
            )
        else:
            raise ValueError(f"No fallback defined for schema: {schema.__name__}")


# ===== Example Usage =====

if __name__ == "__main__":
    # Example 1: Parse validation result
    vlm_response_1 = """
    Here's my analysis:
    
    ```json
    {
        "format_issues": ["Images need descriptions", "Tables should be bullets"],
        "missing_content": ["Page 5 content missing"],
        "improvement_suggestions": ["Add citations", "Use questions as headings"],
        "confidence": 0.85
    }
    ```
    
    That's my assessment.
    """
    
    result = parse_vlm_response(
        vlm_response_1,
        ValidationResult,
        verbose=True
    )
    print("Validation Result:")
    print(f"  Format issues: {len(result.format_issues)}")
    print(f"  Confidence: {result.confidence}")
    
    # Example 2: Parse with fallback
    bad_response = "I couldn't analyze this properly due to an error."
    
    result_with_fallback = parse_vlm_response(
        bad_response,
        ValidationResult,
        fallback=ValidationResult(
            format_issues=["VLM analysis failed"],
            confidence=0.0
        ),
        verbose=True
    )
    print("\nWith fallback:")
    print(f"  Format issues: {result_with_fallback.format_issues}")
    
    # Example 3: Generate schema-enforced prompt
    prompt = "Analyze this markdown content for issues."
    enhanced_prompt = enforce_pydantic_schema(prompt, ValidationResult)
    print("\nEnhanced prompt (first 200 chars):")
    print(enhanced_prompt[:200])
