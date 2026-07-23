from docx import Document
from lxml import etree

from pipeline.review.annotator import _get_or_create_comments_part


def test_new_comments_part_has_single_well_formed_root():
    document = Document()

    root = _get_or_create_comments_part(document)

    assert etree.QName(root).localname == "comments"
    reparsed = etree.fromstring(etree.tostring(root))
    assert etree.QName(reparsed).localname == "comments"
