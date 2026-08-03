using System;
using System.IO;

namespace XXAR.Uninstall
{
    // Every path and well-known name the uninstaller touches, resolved in one place.
    public static class RemovalLocations
    {
        public const string ProductName = "XXAR";
        public const string ProductKey = @"Software\XXAR";
        public const string ArpKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\XXAR";
        public const string LauncherFileName = "XXAR.exe";
        public const string PayloadFolderName = "resources";

        // Machine-local data the app writes itself; the installer never shipped any of it.
        public static readonly string[] RuntimeDataFolders = { "tools", "cache", "state", "updates", "logs" };

        public static string LocalDataRoot
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), ProductName);
            }
        }

        public static string UserDataRoot
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), ProductName);
            }
        }

        public static string StartMenuFolder
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    @"Microsoft\Windows\Start Menu\Programs\" + ProductName);
            }
        }

        public static string PayloadFolderIn(string root)
        {
            return Path.Combine(root, PayloadFolderName);
        }

        public static string LauncherIn(string root)
        {
            return Path.Combine(root, PayloadFolderName, LauncherFileName);
        }
    }
}
