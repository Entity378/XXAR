using System;
using System.IO;

namespace XXAR.Wizard
{
    public class AppRunningException : Exception { }

    // Windows keeps a running executable's image locked, so failing to open it for writing answers
    // exactly the question being asked: can these files be replaced or removed right now.
    public static class AppLock
    {
        public static bool IsRunning(string executablePath)
        {
            if (!File.Exists(executablePath)) return false;

            try
            {
                using (File.Open(executablePath, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) return false;
            }
            catch (IOException) { return true; }
            catch (UnauthorizedAccessException) { return true; }
        }

        public static void ThrowIfRunning(string executablePath)
        {
            if (IsRunning(executablePath)) throw new AppRunningException();
        }
    }
}
