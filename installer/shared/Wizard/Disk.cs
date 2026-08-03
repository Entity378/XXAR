using System;
using System.IO;
using System.Linq;

namespace XXAR.Wizard
{
    // File operations that must never throw out of a job: a folder that cannot be deleted is logged
    // and stepped over, because failing halfway through a removal is worse than leaving a leftover.
    public static class Disk
    {
        public static void DeleteTree(string path)
        {
            try
            {
                if (Directory.Exists(path)) Directory.Delete(path, recursive: true);
            }
            catch (Exception ex)
            {
                Journal.Error($"delete failed for {path}", ex);
            }
        }

        public static void DeleteFile(string path)
        {
            try { File.Delete(path); }
            catch (Exception ex) { Journal.Error($"delete failed for {path}", ex); }
        }

        public static string[] FilesIn(string path)
        {
            try { return Directory.Exists(path) ? Directory.GetFiles(path) : new string[0]; }
            catch { return new string[0]; }
        }

        public static string[] FoldersIn(string path)
        {
            try { return Directory.Exists(path) ? Directory.GetDirectories(path) : new string[0]; }
            catch { return new string[0]; }
        }

        public static long SizeOf(string path)
        {
            try
            {
                if (!Directory.Exists(path)) return 0;
                return new DirectoryInfo(path).EnumerateFiles("*", SearchOption.AllDirectories)
                                              .Sum(file => file.Length);
            }
            catch
            {
                // An unreadable subtree only makes an estimate low; it must never stop a run.
                return 0;
            }
        }

        public static void DeleteIfEmpty(string path)
        {
            try
            {
                if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any())
                    Directory.Delete(path);
            }
            catch { }
        }

        // Windows will not delete a running image, and a per-user program cannot register a
        // delete-at-reboot because that list lives under HKLM. Renaming empties the folder now.
        public static void MoveOutOfTheWay(string executablePath)
        {
            try
            {
                var parkedName = "XXAR-Uninstall-" + Guid.NewGuid().ToString("N") + ".tmp";
                var tempFolder = Path.GetTempPath();
                // A cross-volume move copies then deletes, and deleting a running image fails, so stay put.
                bool sameVolume = string.Equals(Path.GetPathRoot(tempFolder), Path.GetPathRoot(executablePath),
                                                StringComparison.OrdinalIgnoreCase);
                var parkedPath = Path.Combine(
                    sameVolume ? tempFolder : Path.GetDirectoryName(executablePath), parkedName);

                File.Move(executablePath, parkedPath);
            }
            catch (Exception ex)
            {
                Journal.Error("could not move the running executable out of the install folder", ex);
            }
        }
    }
}
