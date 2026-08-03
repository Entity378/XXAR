using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace XXAR.Setup
{
    // What the setup carries, read from the trailer the build appends.
    public class PayloadInfo
    {
        public long ZipOffset;
        public string Version;
    }

    // The build appends the payload zip to the stub, followed by a 48-byte trailer:
    // magic "XXARSFX2" (8) + zip offset as int64 little-endian (8) + version as NUL-padded ASCII (32).
    public static class PayloadReader
    {
        private const string Magic = "XXARSFX2";
        private const int VersionFieldSize = 32;
        private const int TrailerSize = 8 + 8 + VersionFieldSize;

        // Returns null when the executable carries no payload, as is the case for the installed uninstaller.
        public static PayloadInfo FindPayload(string exePath)
        {
            try
            {
                using (var fs = File.OpenRead(exePath))
                {
                    if (fs.Length < TrailerSize) return null;
                    fs.Seek(-TrailerSize, SeekOrigin.End);
                    var trailer = new byte[TrailerSize];
                    if (fs.Read(trailer, 0, TrailerSize) != TrailerSize) return null;
                    if (Encoding.ASCII.GetString(trailer, 0, 8) != Magic) return null;

                    long offset = BitConverter.ToInt64(trailer, 8);
                    if (offset <= 0 || offset >= fs.Length - TrailerSize) return null;

                    return new PayloadInfo
                    {
                        ZipOffset = offset,
                        Version = Encoding.ASCII.GetString(trailer, 16, VersionFieldSize).TrimEnd('\0').Trim(),
                    };
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
            // The window stops before the trailer so the zip reader finds its end-of-directory record at the true end.
            var zipStream = new SubStream(fs, offset, fs.Length - TrailerSize - offset);
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
