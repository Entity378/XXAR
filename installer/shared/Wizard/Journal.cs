using System;
using System.IO;

namespace XXAR.Wizard
{
    // Plain-text log in %TEMP%, opened by the final step's "View log" button.
    // Shared by both programs, so the file name is handed in at startup.
    public static class Journal
    {
        public static string Path { get; private set; }

        public static void Start(string fileName, string title)
        {
            Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), fileName);
            // Logging must never be the reason a run fails, so every write is best-effort.
            try { File.WriteAllText(Path, $"{title} - {DateTime.Now:yyyy-MM-dd HH:mm:ss}\r\n"); }
            catch { }
        }

        public static void Info(string message)
        {
            Append("INFO ", message);
        }

        public static void Error(string message, Exception cause = null)
        {
            Append("ERROR", cause == null ? message : $"{message}: {cause}");
        }

        private static void Append(string level, string message)
        {
            if (Path == null) return;
            try { File.AppendAllText(Path, $"[{DateTime.Now:HH:mm:ss}] {level} {message}\r\n"); }
            catch { }
        }
    }
}
