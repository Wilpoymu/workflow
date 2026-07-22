"""Unit tests for Gemini JSON parsing logic.

Tests ``_parse_analysis_json()`` which extracts structured ``GeminiAnalysis``
from raw Gemini Web responses. This is a critical function because Gemini
frequently wraps JSON in markdown fences, adds extra commentary, or produces
malformed JSON that needs ``json_repair`` fallback.
"""

from app.models.thumbnail import GeminiAnalysis
from app.services.thumbnail_service import _parse_analysis_json

# ─── Valid JSON fixtures ───────────────────────────────────────

VALID_JSON = """{
    "primary_subject": "a dark forest path at midnight",
    "mood_emotion": "mysterious, suspenseful",
    "recommended_colors": {
        "background": "#0d0d1a",
        "text": "#FFFFFF",
        "accent": "#ff4444"
    },
    "recommended_text": "¡No te lo pierdas!",
    "composition": "lower_third",
    "background_image_hint": "A dark forest path illuminated by moonlight, fog, mysterious atmosphere, cinematic lighting"
}"""

VALID_JSON_WITH_VARIANTS = """{
    "primary_subject": "a detective in a dark alley",
    "mood_emotion": "suspenseful, thrilling",
    "recommended_colors": {
        "background": "#1a1a2e",
        "text": "#FFFFFF",
        "accent": "#e94560"
    },
    "recommended_text": "El misterio continúa",
    "composition": "centered",
    "background_image_hint": "Noir detective under streetlamp, rain, dramatic shadows",
    "variant_suggestions": [
        {
            "hook_text": "¿Quién lo hizo?",
            "color_accent": "#ff6b35",
            "text_position": "lower_third"
        },
        {
            "hook_text": "Nunca lo adivinarás",
            "color_accent": "#f7c59f",
            "text_position": "top_aligned"
        }
    ]
}"""


class TestParseAnalysisJson:
    """Tests for ``_parse_analysis_json()`` — Gemini output → GeminiAnalysis parsing."""

    # ── Valid JSON ─────────────────────────────────────────

    def test_valid_json_returns_analysis(self):
        """A perfectly valid JSON should parse into a complete GeminiAnalysis."""
        result = _parse_analysis_json(VALID_JSON)
        assert result is not None
        assert isinstance(result, GeminiAnalysis)
        assert result.primary_subject == "a dark forest path at midnight"
        assert result.mood_emotion == "mysterious, suspenseful"
        assert result.recommended_colors["background"] == "#0d0d1a"
        assert result.recommended_colors["text"] == "#FFFFFF"
        assert result.recommended_colors["accent"] == "#ff4444"
        assert result.recommended_text == "¡No te lo pierdas!"
        assert result.composition == "lower_third"
        assert "moonlight" in result.background_image_hint

    def test_valid_json_with_variants(self):
        """JSON with variant_suggestions should parse all variant data."""
        result = _parse_analysis_json(VALID_JSON_WITH_VARIANTS)
        assert result is not None
        assert result.variant_suggestions is not None
        assert len(result.variant_suggestions) == 2
        assert result.variant_suggestions[0]["hook_text"] == "¿Quién lo hizo?"
        assert result.variant_suggestions[1]["hook_text"] == "Nunca lo adivinarás"

    # ── Extra text wrapping (realistic Gemini behavior) ────

    def test_extra_text_before_and_after_json(self):
        """Gemini often adds explanatory text around the JSON."""
        raw = (
            "Here is the thumbnail analysis you requested:\n\n"
            + VALID_JSON
            + "\n\nLet me know if you'd like any adjustments!"
        )
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a dark forest path at midnight"
        assert result.recommended_text == "¡No te lo pierdas!"

    def test_markdown_code_fences(self):
        """Gemini sometimes wraps JSON in ```json ... ``` code fences."""
        raw = f"```json\n{VALID_JSON}\n```"
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a dark forest path at midnight"

    def test_json_code_fences_no_language(self):
        """Gemini sometimes uses plain ``` without 'json' label."""
        raw = f"```\n{VALID_JSON}\n```"
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a dark forest path at midnight"

    def test_multiple_paragraphs_around_json(self):
        """Multiple paragraphs of Gemini preamble should be tolerated."""
        raw = (
            "I have analyzed your script carefully.\n\n"
            "Based on the content, here are my recommendations:\n\n"
            + VALID_JSON
            + "\n\nPlease let me know if you need any changes."
        )
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a dark forest path at midnight"

    # ── Malformed JSON (json_repair fallback) ──────────────

    def test_trailing_commas_in_object(self):
        """Trailing commas in objects should be repaired by json_repair."""
        raw = """{
            "primary_subject": "a mountain summit",
            "mood_emotion": "triumphant, epic",
            "recommended_colors": {
                "background": "#0a0a1a",
                "text": "#FFFFFF",
                "accent": "#ff6600",
            },
            "recommended_text": "¡Cima alcanzada!",
            "composition": "centered",
            "background_image_hint": "Mount Everest summit at sunrise, clouds below, golden light",
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a mountain summit"
        assert result.recommended_text == "¡Cima alcanzada!"

    def test_trailing_commas_in_array(self):
        """Trailing commas in arrays should be repaired."""
        raw = """{
            "primary_subject": "ocean depths",
            "mood_emotion": "peaceful",
            "recommended_colors": {"background": "#001a2e", "text": "#FFFFFF", "accent": "#00d4ff"},
            "recommended_text": "Océano profundo",
            "composition": "lower_third",
            "background_image_hint": "deep ocean",
            "variant_suggestions": [
                {"hook_text": "Opción 1", "color_accent": "#ff0000", "text_position": "top"},
                {"hook_text": "Opción 2", "color_accent": "#00ff00", "text_position": "center"},
            ]
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.variant_suggestions is not None
        assert len(result.variant_suggestions) == 2

    def test_unquoted_keys(self):
        """Unquoted JS-style keys should be repaired by json_repair."""
        raw = """{
            primary_subject: "underwater cave",
            mood_emotion: "peaceful, mysterious",
            "recommended_colors": {
                background: "#001a2e",
                "text": "#FFFFFF",
                "accent": "#00d4ff"
            },
            "recommended_text": "Explora lo desconocido",
            "composition": "lower_third",
            "background_image_hint": "Underwater cave with sunbeams, crystal clear water"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "underwater cave"

    def test_missing_quotes_around_string_value(self):
        """Missing quotes around a string value should trigger repair."""
        raw = """{
            "primary_subject": "sunset beach",
            "mood_emotion": calm,
            "recommended_colors": {"background": "#1a1a2e", "text": "#FFFFFF", "accent": "#ff6600"},
            "recommended_text": "Atardecer mágico",
            "composition": "lower_third",
            "background_image_hint": "Sunset over tropical beach, golden hour, warm colors"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        # The exact value for mood_emotion depends on the repair, but the function shouldn't crash
        assert isinstance(result, GeminiAnalysis)

    def test_multiple_json_repair_issues_combined(self):
        """Multiple JSON issues (commas + missing quotes + unquoted keys) combined."""
        raw = """{
            primary_subject: neon_skyline,
            mood_emotion: "energetic, vibrant",
            "recommended_colors": {
                "background": "#0a0a1a",
                "text": "#FFFFFF",
                "accent": "#00ff88",
            },
            "recommended_text": "Noche en la ciudad",
            "composition": top_aligned,
            "background_image_hint": "Neon-lit city skyline, rain reflections, cyberpunk atmosphere",
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        # The repair may not get everything right, but it shouldn't crash
        assert isinstance(result, GeminiAnalysis)

    # ── Non-JSON / error cases ──────────────────────────────

    def test_completely_non_json_response_returns_none(self):
        """A completely non-JSON response should return None (not raise)."""
        raw = "I'm sorry, I cannot analyze this script. Please provide a different script."
        result = _parse_analysis_json(raw)
        assert result is None

    def test_empty_string_returns_none(self):
        """An empty string should return None."""
        result = _parse_analysis_json("")
        assert result is None

    def test_only_whitespace_returns_none(self):
        """A whitespace-only response should return None."""
        result = _parse_analysis_json("   \n\n   \t   ")
        assert result is None

    def test_html_like_response_returns_none(self):
        """If Gemini returns HTML instead of JSON, should return None."""
        raw = "<html><body>Error: Script too long</body></html>"
        result = _parse_analysis_json(raw)
        assert result is None

    def test_single_word_response_returns_none(self):
        """A random single word should return None."""
        result = _parse_analysis_json("No.")
        assert result is None

    # ── Partial / minimal data ─────────────────────────────

    def test_partial_data_missing_optional_fields(self):
        """Missing optional fields should get default values without error."""
        raw = """{
            "primary_subject": "a busy city street",
            "mood_emotion": "energetic"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a busy city street"
        assert result.mood_emotion == "energetic"
        # Optional fields should default gracefully
        assert result.recommended_text == ""
        assert result.composition == "lower_third"  # default from _parse_analysis_json
        assert result.recommended_colors == {}
        assert result.background_image_hint == ""

    def test_only_primary_subject(self):
        """Even just a primary_subject should parse into a valid analysis."""
        raw = '{"primary_subject": "a sunset"}'
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a sunset"
        assert result.composition == "lower_third"  # default
        assert result.recommended_text == ""

    # ── Field name normalization ──────────────────────────

    def test_normalizes_spaces_in_field_names(self):
        """Field names with spaces should be normalized to underscores."""
        raw = """{
            "primary subject": "a rainy street",
            "mood emotion": "melancholic",
            "recommended colors": {"background": "#111", "text": "#FFF", "accent": "#ff4444"},
            "recommended text": "Lluvia eterna",
            "composition": "lower_third",
            "background image hint": "Rainy city street at night, reflections on wet pavement"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a rainy street"
        assert result.mood_emotion == "melancholic"

    def test_case_insensitive_field_names(self):
        """Field names with different casing should still be recognized."""
        raw = """{
            "Primary_Subject": "a desert landscape",
            "Mood_Emotion": "lonely, vast",
            "Recommended_Colors": {"background": "#1a1a2e", "text": "#FFFFFF", "accent": "#ff6600"},
            "Recommended_Text": "Desierto infinito",
            "composition": "centered",
            "background_image_hint": "Endless sand dunes at sunset, warm orange light"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a desert landscape"
        assert result.mood_emotion == "lonely, vast"

    def test_dash_to_underscore_normalization(self):
        """Field names with dashes (e.g. 'primary-subject') should be normalized."""
        raw = """{
            "primary-subject": "a snowy mountain",
            "mood-emotion": "peaceful, serene"
        }"""
        result = _parse_analysis_json(raw)
        assert result is not None
        assert result.primary_subject == "a snowy mountain"
        assert result.mood_emotion == "peaceful, serene"
