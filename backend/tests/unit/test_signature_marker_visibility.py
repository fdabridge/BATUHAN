from __future__ import annotations

from audit_set.signature_marker_visibility import (
    erase_marker_boxes,
    marker_hide_boxes,
    paint_marker_boxes,
    signature_marker_candidates,
)


class FakePage:
    rect = (0, 0, 200, 200)

    def __init__(self, *, matches=None, words=None, fail_words=False):
        self.matches = matches or {}
        self.words = words or []
        self.fail_words = fail_words

    def search_for(self, marker, clip=None):
        return self.matches.get(marker, [])

    def get_text(self, kind, clip=None):
        assert kind == "words"
        if self.fail_words:
            raise RuntimeError("text extraction unavailable")
        return self.words


def test_signature_marker_candidates_include_canonical_and_legacy_aliases():
    candidates = signature_marker_candidates("CB_CERT_MANAGER")

    assert "[SIG:CB_CERT_MANAGER]" in candidates
    assert "[SIG:CB_REVIEWER]" in candidates
    assert "[SIG:CERT_MANAGER_FR233]" in candidates


def test_exact_search_keeps_wrapped_match_rectangles_separate():
    marker = "[SIG:ORG_OPENING_ORG_EMP_1]"
    page = FakePage(matches={
        marker: [(10, 10, 70, 20), (10, 22, 28, 32)],
    })

    boxes = marker_hide_boxes(page, (10, 10, 70, 32), [marker])

    assert boxes == [
        (9.4, 9.4, 70.6, 20.6),
        (9.4, 21.4, 28.6, 32.6),
    ]


def test_wrapped_word_fallback_masks_each_marker_line_not_the_whole_cell():
    page = FakePage(words=[
        (10, 10, 70, 20, "[SIG:ORG_OPENING_ORG_EM", 0, 0, 0),
        (10, 22, 28, 32, "P_1]", 0, 1, 0),
        (100, 10, 150, 20, "Unrelated", 1, 0, 0),
    ])

    boxes = marker_hide_boxes(
        page,
        (10, 10, 70, 32),
        ["[SIG:ORG_OPENING_ORG_EMP_1]"],
    )

    assert boxes == [
        (9.4, 9.4, 70.6, 20.6),
        (9.4, 21.4, 28.6, 32.6),
    ]


def test_stored_coordinates_are_the_final_visibility_fallback():
    page = FakePage(fail_words=True)

    boxes = marker_hide_boxes(
        page,
        (10, 10, 70, 32),
        ["[SIG:ORG_OPENING_ORG_EMP_1]"],
    )

    assert boxes == [(9.75, 9.75, 70.25, 32.25)]


def test_marker_erasure_uses_transparent_text_only_redaction():
    class RedactionPage:
        def __init__(self):
            self.annotations = []
            self.options = None

        def add_redact_annot(self, box, **options):
            self.annotations.append((box, options))

        def apply_redactions(self, **options):
            self.options = options

    page = RedactionPage()
    boxes = [(10, 10, 70, 20), (10, 22, 28, 32)]

    assert erase_marker_boxes(page, boxes) is True
    assert page.annotations == [
        ((10, 10, 70, 20), {"fill": None, "cross_out": False}),
        ((10, 22, 28, 32), {"fill": None, "cross_out": False}),
    ]
    assert page.options == {"images": 0, "graphics": 0, "text": 0}


def test_marker_erasure_falls_back_to_white_paint_for_older_renderers():
    class LegacyPage:
        def __init__(self):
            self.painted = []

        def add_redact_annot(self, box, **options):
            raise AttributeError("redaction API unavailable")

        def draw_rect(self, box, **options):
            self.painted.append((box, options))

    page = LegacyPage()
    box = (10, 10, 70, 20)

    assert erase_marker_boxes(page, [box]) is True
    assert page.painted == [(
        box,
        {
            "color": (1.0, 1.0, 1.0),
            "fill": (1.0, 1.0, 1.0),
            "width": 0,
        },
    )]


def test_cached_viewer_mask_uses_white_paint_without_redaction():
    class ViewerPage:
        def __init__(self):
            self.painted = []

        def draw_rect(self, box, **options):
            self.painted.append((box, options))

    page = ViewerPage()
    box = (10, 10, 70, 20)

    assert paint_marker_boxes(page, [box]) is True
    assert page.painted[0][0] == box
