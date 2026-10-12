from server import AnalyzerHandler


def test_public_interrupt_icons_return_image_bytes_without_authentication():
    handler = AnalyzerHandler.__new__(AnalyzerHandler)
    handler.send_response_body = lambda status, content_type, body: (status, content_type, body)
    handler.send_error = lambda status: (status, "", b"")
    groups = [('png', 'image/png', b'\x89PNG', (6552,1766,147362,2139,57994,47528,183752,97547)),
              ('jpg', 'image/jpeg', b'\xff\xd8', (31935,96231,116705,220543,351338))]
    for ext, mime, signature, spells in groups:
        for spell in spells:
            path = f'/assets/spells/{spell}.{ext}'
            assert AnalyzerHandler.is_public_page(path)
            status, content_type, body = handler.handle_static(path,public=True)
            assert status == 200
            assert content_type == mime
            assert body.startswith(signature)
    for path in ('/assets/spells/example.json','/assets/spells/example.py','/config.json'):
        assert not AnalyzerHandler.is_public_page(path)
