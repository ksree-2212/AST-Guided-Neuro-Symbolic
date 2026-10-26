"""
Unit & Integration Tests for Source File & Folder Ingestion (/api/upload).
Validates:
- Single file upload
- Multiple files upload
- Windows-style absolute and relative paths (e.g. C:\\fakepath\\...)
- Subfolder structures (folder upload)
- Non-UTF-8 character encodings (Latin-1 / ANSI)
"""

import io
import unittest
from starlette.testclient import TestClient
from web_studio.backend.server import app


class TestUploadEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_single_file_upload(self):
        """Test uploading a standard single COBOL file."""
        code = b"IDENTIFICATION DIVISION.\nPROGRAM-ID. HELLO-UPLOAD.\nPROCEDURE DIVISION.\nDISPLAY 'UPLOAD OK'.\n"
        f = io.BytesIO(code)
        res = self.client.post("/api/upload", files=[
            ("files", ("HELLO-UPLOAD.cbl", f, "text/plain"))
        ])
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("uploaded", data)
        self.assertEqual(len(data["uploaded"]), 1)
        self.assertEqual(data["uploaded"][0]["filename"], "HELLO-UPLOAD.cbl")
        self.assertIn("UPLOAD OK", data["uploaded"][0]["content"])

    def test_02_windows_path_upload(self):
        """Test uploading with Windows-style absolute/fakepath filename."""
        code = b"IDENTIFICATION DIVISION.\nPROGRAM-ID. WIN-PATH.\n"
        f = io.BytesIO(code)
        # Browsers on Windows often send C:\\fakepath\\WIN-PATH.cbl
        res = self.client.post("/api/upload", files=[
            ("files", ("C:\\fakepath\\WIN-PATH.cbl", f, "text/plain"))
        ])
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["uploaded"]), 1)
        self.assertEqual(data["uploaded"][0]["filename"], "WIN-PATH.cbl")

    def test_03_folder_upload_multiple_files(self):
        """Test uploading multiple files representing a directory structure."""
        f1 = io.BytesIO(b"IDENTIFICATION DIVISION.\nPROGRAM-ID. MAIN.\n")
        f2 = io.BytesIO(b"01 WS-SHARED PIC X(10).\n")
        
        res = self.client.post("/api/upload", files=[
            ("files", ("myproject/src/MAIN.cbl", f1, "text/plain")),
            ("files", ("myproject/copy/SHARED.cpy", f2, "text/plain"))
        ])
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["uploaded"]), 2)
        filenames = [item["filename"] for item in data["uploaded"]]
        self.assertIn("MAIN.cbl", filenames)
        self.assertIn("SHARED.cpy", filenames)

    def test_04_latin1_encoded_file(self):
        """Test uploading files containing Latin-1 / non-ASCII characters."""
        code = "IDENTIFICATION DIVISION.\nPROGRAM-ID. ACCENT.\n*> Cr\u00e9dit \u00e0 payer\n".encode("latin-1")
        f = io.BytesIO(code)
        res = self.client.post("/api/upload", files=[
            ("files", ("ACCENT.cbl", f, "text/plain"))
        ])
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["uploaded"]), 1)
        self.assertIn("Cr", data["uploaded"][0]["content"])


if __name__ == "__main__":
    unittest.main()
