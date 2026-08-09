using System;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace XXAR.Setup
{
    // The build appends the payload archive to this executable, followed by a 16-byte trailer:
    // magic "XXARSFX1" (8) then the archive's start offset as a little-endian int64 (8).
    public static class SelfExtract
    {
        private const string TrailerMagic = "XXARSFX1";
        private const int TrailerLength = 16;

        // Zero means the executable carries no payload, which is what a truncated download looks like.
        public static long FindArchiveOffset(string executablePath)
        {
            try
            {
                using (var file = File.OpenRead(executablePath))
                {
                    if (file.Length < TrailerLength) return 0;

                    var trailer = new byte[TrailerLength];
                    file.Seek(-TrailerLength, SeekOrigin.End);
                    if (file.Read(trailer, 0, TrailerLength) != TrailerLength) return 0;
                    if (Encoding.ASCII.GetString(trailer, 0, 8) != TrailerMagic) return 0;

                    long offset = BitConverter.ToInt64(trailer, 8);
                    return offset > 0 && offset < file.Length - TrailerLength ? offset : 0;
                }
            }
            catch
            {
                return 0;
            }
        }

        public static ZipArchive OpenArchive(string executablePath, long offset)
        {
            var file = File.OpenRead(executablePath);
            // The window stops before the trailer so the archive reader finds its end-of-directory
            // record where it expects it, at the very end of the stream it was handed.
            var archiveBytes = new FileWindow(file, offset, file.Length - TrailerLength - offset);
            return new ZipArchive(archiveBytes, ZipArchiveMode.Read, leaveOpen: false);
        }

        // Read-only view of [start, start + length) of an underlying seekable stream.
        private sealed class FileWindow : Stream
        {
            private readonly Stream source;
            private readonly long start;
            private readonly long length;

            public FileWindow(Stream source, long start, long length)
            {
                this.source = source;
                this.start = start;
                this.length = length;
                source.Seek(start, SeekOrigin.Begin);
            }

            public override bool CanRead => true;
            public override bool CanSeek => true;
            public override bool CanWrite => false;
            public override long Length => length;

            public override long Position
            {
                get { return source.Position - start; }
                set { source.Position = start + value; }
            }

            public override int Read(byte[] buffer, int offset, int count)
            {
                long left = length - Position;
                if (left <= 0) return 0;
                return source.Read(buffer, offset, count > left ? (int)left : count);
            }

            public override long Seek(long offset, SeekOrigin origin)
            {
                switch (origin)
                {
                    case SeekOrigin.Begin: Position = offset; break;
                    case SeekOrigin.Current: Position += offset; break;
                    default: Position = length + offset; break;
                }
                return Position;
            }

            public override void Flush() { }
            public override void SetLength(long value) { throw new NotSupportedException(); }
            public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }

            protected override void Dispose(bool disposing)
            {
                if (disposing) source.Dispose();
                base.Dispose(disposing);
            }
        }
    }
}
