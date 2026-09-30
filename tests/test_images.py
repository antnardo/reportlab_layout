"""Reading and scaling images."""

import io

import pytest
from PIL import Image as PILImage

from reportlab_layout import PDFMaker
from reportlab_layout.images import ImageSpec, image_spec, inline_image, load_image


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


@pytest.fixture
def pil_image():
    """A 60x40 image, blue on a fully transparent ground."""
    image = PILImage.new("RGBA", (60, 40), (255, 0, 0, 0))
    image.paste((0, 0, 255, 255), (10, 10, 50, 30))
    return image


class TestFromMemory:
    """An image needs no file: bytes, an open file or a Pillow image all work."""

    def test_a_pillow_image_gives_its_size(self, pil_image):
        spec = image_spec(pil_image)
        assert (spec.width, spec.height) == (60, 40)

    def test_a_pillow_image_is_held_as_data_not_a_path(self, pil_image):
        spec = image_spec(pil_image)
        assert spec.path is None
        assert spec.data.startswith(b"\x89PNG")

    def test_bytes_are_read(self, pil_image):
        buffer = io.BytesIO()
        pil_image.save(buffer, "PNG")
        assert image_spec(buffer.getvalue()).width == 60

    def test_an_open_binary_file_is_read(self, picture):
        with picture.open("rb") as handle:
            spec = image_spec(handle)
        assert (spec.width, spec.height) == (200, 100)
        assert spec.path is None

    def test_a_spec_passes_through_unchanged(self, picture):
        spec = image_spec(picture)
        assert image_spec(spec) is spec

    def test_a_file_is_still_held_as_a_path(self, picture):
        spec = image_spec(picture)
        assert spec.path == picture
        assert spec.data is None

    def test_the_flowable_is_sized_from_memory(self, pil_image):
        image = load_image(pil_image, width=90)
        assert (image.drawWidth, image.drawHeight) == pytest.approx((90, 60))

    def test_the_same_spec_draws_twice(self, pil_image, doc):
        """Each call gets a fresh buffer, so the second is not reading past the end."""
        spec = image_spec(pil_image)
        first = doc.draw_image(spec, width=30)
        second = doc.draw_image(spec, width=30)
        assert tuple(first)[2:] == pytest.approx(tuple(second)[2:])

    def test_inline_image_refuses_an_image_without_a_file(self, pil_image):
        with pytest.raises(ValueError, match="needs an image on disk"):
            inline_image(pil_image, width=10, height=10)


@pytest.mark.ink
class TestTransparency:
    def test_only_the_opaque_part_inks_the_page(self, tmp_path, pil_image, ink):
        """The alpha channel survives the trip through reportlab.

        The image is 60x40 with a transparent ground and an opaque rectangle
        from (10, 10) to (50, 30). Drawn at (30, 25) with no scaling, only that
        rectangle should mark the page: ink from (40, 35) to (80, 55). Were the
        alpha lost, the whole 60x40 frame would come out red and opaque.
        """
        path = tmp_path / "alpha.pdf"
        doc = PDFMaker(path, pagesize=(120, 90), left=0, right=0, top=0, bottom=0)
        doc.draw_image(pil_image, width=60, x=30, y=25, absolute=True)
        doc.save()
        assert ink(path, dpi=300) == pytest.approx((40, 35, 80, 55), abs=1)
