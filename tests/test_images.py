"""Reading and scaling images."""

import pytest

from reportlab_layout.images import ImageSpec, image_spec, load_image


class TestImageSpec:
    def test_reads_pixel_dimensions(self, picture):
        spec = image_spec(picture)
        assert (spec.width, spec.height) == (200, 100)

    def test_aspect_is_height_over_width(self, picture):
        assert image_spec(picture).aspect == pytest.approx(0.5)

    def test_width_alone_preserves_aspect(self, picture):
        assert image_spec(picture).scaled(width=50) == pytest.approx((50, 25))

    def test_height_alone_preserves_aspect(self, picture):
        assert image_spec(picture).scaled(height=50) == pytest.approx((100, 50))

    def test_scale_multiplies_both_sides(self, picture):
        assert image_spec(picture).scaled(scale=0.25) == pytest.approx((50, 25))

    def test_both_sides_given_forces_the_ratio(self, picture):
        assert image_spec(picture).scaled(width=30, height=90) == pytest.approx((30, 90))

    def test_scale_with_width_is_rejected(self, picture):
        with pytest.raises(ValueError, match="exclusive"):
            image_spec(picture).scaled(width=10, scale=2)

    def test_no_constraint_is_rejected(self, picture):
        with pytest.raises(ValueError, match="width, height or scale"):
            image_spec(picture).scaled()


class TestLoadImage:
    def test_sizes_the_flowable(self, picture):
        image = load_image(image_spec(picture), width=80)
        assert (image.drawWidth, image.drawHeight) == pytest.approx((80, 40))

    def test_accepts_a_bare_path(self, picture):
        image = load_image(picture, width=80)
        assert image.drawHeight == pytest.approx(40)

    def test_spec_is_immutable(self, picture):
        spec = image_spec(picture)
        with pytest.raises((AttributeError, TypeError)):
            spec.width = 1  # type: ignore[misc]

    def test_spec_is_a_dataclass_not_a_dict(self, picture):
        assert isinstance(image_spec(picture), ImageSpec)
