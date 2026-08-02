using System;
using System.IO;

namespace XXAR.Setup
{
    // Plain-text log in %TEMP%, surfaced by the exit page's "View log" button.
    public static class SetupLog
    {
        public static readonly string Path =
            System.IO.Path.Combine(System.IO.Path.GetTempPath(), "XXAR-Setup.log");

        static SetupLog()
        {
            try { File.WriteAllText(Path, $"XXAR Setup log — {DateTime.Now:yyyy-MM-dd HH:mm:ss}\r\n"); }
            catch { }
        }

        public static void Info(string message) => Write("INFO ", message);

        public static void Error(string message, Exception ex = null)
            => Write("ERROR", ex == null ? message : $"{message}: {ex}");

        private static void Write(string level, string message)
        {
            try { File.AppendAllText(Path, $"[{DateTime.Now:HH:mm:ss}] {level} {message}\r\n"); }
            catch { }
        }
    }
}
