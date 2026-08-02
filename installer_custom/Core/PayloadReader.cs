using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace XXAR.Setup
{
    // The build appends the portable zip to the stub exe, followed by a 16-byte trailer:
    // 8-byte magic "XXARSFX1" + int64 little-endian offset where the zip starts (= stub length).
    public static class PayloadReader
    {
        private const string Magic = "XXARSFX1";

        // Returns the stub length (zip start) or -1 when the exe carries no payload (uninstaller copy).
        public static long FindPayloadOffset(string exePath)
        {
            using (var fs = File.OpenRead(exePath))
            {
                if (fs.Length < 16) return -1;
                fs.Seek(-16, SeekOrigin.End);
                var trailer = new byte[16];
                if (fs.Read(trailer, 0, 16) != 16) return -1;
                if (Encoding.ASCII.GetString(trailer, 0, 8) != Magic) return -1;
                long offset = BitConverter.ToInt64(trailer, 8);
                return offset > 0 && offset < fs.Length - 16 ? offset : -1;
            }
        }

        // The version travels in the payload rather than in the stub's own resources, so the stub does not
        // have to be recompiled for a new XXAR release. Reading it only touches the zip's central directory.
        public static string ReadPayloadVersion(string exePath, long offset)
        {
            try
            {
                using (var zip = OpenPayload(exePath, offset))
                {
                    var entry = zip.GetEntry("version.txt");
                    if (entry == null) return null;
                    using (var reader = new StreamReader(entry.Open()))
                        return reader.ReadToEnd().Trim();
                }
            }
            catch
            {
                return null;
            }
        }

        public static ZipArchive OpenPayload(string exePath, long offset)
        {
            var fs = File.OpenRead(exePath);
            // The sub-stream ends before the trailer so the zip reader finds its end-of-directory record at the true end.
            var zipStream = new SubStream(fs, offset, fs.Length - 16 - offset);
            return new ZipArchive(zipStream, ZipArchiveMode.Read, leaveOpen: false);
        }

        // Read-only window over [origin, origin+length) of an underlying stream.
        private sealed class SubStream : Stream
        {
            private readonly Stream inner;
            private readonly long origin;
            private readonly long length;

            public SubStream(Stream inner, long origin, long length)
            {
                this.inner = inner;
                this.origin = origin;
                this.length = length;
                inner.Seek(origin, SeekOrigin.Begin);
            }

            public override bool CanRead => true;
            public override bool CanSeek => true;
            public override bool CanWrite => false;
            public override long Length => length;

            public override long Position
            {
                get => inner.Position - origin;
                set => inner.Position = origin + value;
            }

            public override int Read(byte[] buffer, int offset, int count)
            {
                long remaining = length - Position;
                if (remaining <= 0) return 0;
                if (count > remaining) count = (int)remaining;
                return inner.Read(buffer, offset, count);
            }

            public override long Seek(long offset, SeekOrigin seekOrigin)
            {
                switch (seekOrigin)
                {
                    case SeekOrigin.Begin: Position = offset; break;
                    case SeekOrigin.Current: Position += offset; break;
                    default: Position = length + offset; break;
                }
                return Position;
            }

            public override void Flush() { }
            public override void SetLength(long value) => throw new NotSupportedException();
            public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

            protected override void Dispose(bool disposing)
            {
                if (disposing) inner.Dispose();
                base.Dispose(disposing);
            }
        }
    }
}
