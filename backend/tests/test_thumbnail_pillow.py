"""Unit tests for thumbnail Pillow composition logic.

Tests the core image manipulation pipeline:
- ``compose_thumbnail()`` — background + gradient + text overlay
- ``_create_gradient_background()`` — fallback gradient generation
"""

import pytest
import tempfile
from pathlib import Path

from PIL import Image

from app.services.thumbnail_service import (
    THUMBNAIL_HEIGHT,
    THUMBNAIL_WIDTH,
    _create_gradient_background,
    compose_thumbnail,
)
from tests.conftest import make_minimal_analysis


class TestComposeThumbnail:
    """Tests for ``compose_thumbnail()`` — the full Pillow composition pipeline."""

    # ── Happy path ─────────────────────────────────────────

    def test_returns_true_with_valid_inputs(self):
        """``compose_thumbnail()`` should return True when all inputs are valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.png"
            analysis = make_minimal_analysis()
            result = compose_thumbnail(
                project_dir=tmpdir,
                analysis=analysis,
                background_path=None,
                output_path=str(output_path),
            )
            assert result is True

    def test_output_file_exists(self):
        """The output file should exist on disk after composition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.png"
            analysis = make_minimal_analysis()
            compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert output_path.exists(), "Output file was not created"

    def test_output_is_png_format(self):
        """The saved image should be a valid PNG."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.png"
            analysis = make_minimal_analysis()
            compose_thumbnail(tmpdir, analysis, None, str(output_path))
            with Image.open(output_path) as img:
                assert img.format == "PNG", f"Expected PNG, got {img.format}"

    def test_output_is_exactly_1280x720(self):
        """Thumbnail output must be exactly the YouTube-recommended 1280×720."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.png"
            analysis = make_minimal_analysis()
            compose_thumbnail(tmpdir, analysis, None, str(output_path))
            with Image.open(output_path) as img:
                assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (
                    f"Expected ({THUMBNAIL_WIDTH}×{THUMBNAIL_HEIGHT}), got {img.size}"
                )

    # ── Gradient fallback ──────────────────────────────────

    def test_gradient_fallback_with_no_background(self):
        """Should produce a valid thumbnail when background_path is None (gradient fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "gradient.png"
            analysis = make_minimal_analysis()
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True
            with Image.open(output_path) as img:
                assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    def test_gradient_fallback_with_missing_file(self):
        """Should fall back to gradient when background_path points to a non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "fallback.png"
            fake_bg = str(Path(tmpdir) / "nonexistent.png")
            analysis = make_minimal_analysis()
            result = compose_thumbnail(tmpdir, analysis, fake_bg, str(output_path))
            assert result is True

    def test_gradient_fallback_with_actual_background_file(self):
        """When a valid background image exists, it should be used instead of gradient."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple background image
            bg_path = Path(tmpdir) / "background.png"
            bg_img = Image.new("RGB", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), color=(50, 50, 100))
            bg_img.save(bg_path)

            output_path = Path(tmpdir) / "with_bg.png"
            analysis = make_minimal_analysis()
            result = compose_thumbnail(tmpdir, analysis, str(bg_path), str(output_path))
            assert result is True
            with Image.open(output_path) as img:
                assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    # ── Spanish text ───────────────────────────────────────

    def test_handles_spanish_accents(self):
        """Spanish accented characters (á, é, í, ó, ú) should render without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "accents.png"
            analysis = make_minimal_analysis(
                recommended_text="¡Qué película tan increíble!",
            )
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True

    def test_handles_spanish_ene(self):
        """The ñ character should render without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ene.png"
            analysis = make_minimal_analysis(
                recommended_text="Años de experiencia única",
            )
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True

    def test_handles_spanish_question_and_exclamation(self):
        """Spanish opening ¿ and ¡ should render without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "puntuacion.png"
            analysis = make_minimal_analysis(
                recommended_text="¿Qué pasó? ¡No lo sé!",
            )
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True

    # ─── Composition layouts ────────────────────────────────

    @pytest.mark.parametrize("compo", ["lower_third", "centered", "top_aligned", "rule_of_thirds"])
    def test_all_composition_layouts(self, compo: str):
        """All composition layouts should produce a valid thumbnail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / f"{compo}.png"
            analysis = make_minimal_analysis(composition=compo)
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True, f"Composition '{compo}' failed"
            with Image.open(output_path) as img:
                assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    # ─── Custom colors ─────────────────────────────────────

    def test_with_custom_colors(self):
        """Custom color palette should be applied without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "custom_colors.png"
            analysis = make_minimal_analysis(
                recommended_colors={
                    "background": "#0a1628",
                    "text": "#FFD700",
                    "accent": "#FF6347",
                },
            )
            result = compose_thumbnail(tmpdir, analysis, None, str(output_path))
            assert result is True


class TestCreateGradientBackground:
    """Tests for ``_create_gradient_background()`` — the fallback gradient generator."""

    def test_creates_correct_size(self):
        """Gradient should fill the full thumbnail canvas."""
        img = _create_gradient_background("#1a1a2e", "#e94560")
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    def test_returns_rgb_image(self):
        """Gradient should be a standard RGB image."""
        img = _create_gradient_background("#1a1a2e", "#e94560")
        assert img.mode == "RGB"

    def test_gradient_is_vertically_smooth(self):
        """Top and bottom pixels should differ (gradient effect)."""
        img = _create_gradient_background("#000000", "#FFFFFF")
        top_pixel = img.getpixel((0, 0))
        bottom_pixel = img.getpixel((0, THUMBNAIL_HEIGHT - 1))
        # Top should be dark, bottom should be light
        assert sum(top_pixel) < sum(bottom_pixel), "Gradient should go from dark to light"

    def test_handles_three_character_hex(self):
        """3-character shorthand hex codes should be accepted."""
        img = _create_gradient_background("#fff", "#000")
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
        assert img.mode == "RGB"

    def test_invalid_hex_falls_back_gracefully(self):
        """Invalid hex color strings should not crash; fallback color is used."""
        img = _create_gradient_background("not-a-color", "also-invalid")
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    def test_invalid_hex_length_does_not_crash(self):
        """Hex strings with invalid length (e.g. 1 character) should not crash."""
        img = _create_gradient_background("#a", "#bcdef12")
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    def test_same_color_no_error(self):
        """Identical background and accent colors should not cause issues."""
        img = _create_gradient_background("#ff0000", "#ff0000")
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
