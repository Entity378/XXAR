using System;
using System.IO;

namespace XXAR.Setup
{
    // Every path and well-known name the installer touches, resolved in one place so no other
    // file has to build one by hand.
    public static class InstallLocations
    {
        public const string ProductName = "XXAR";
        public const string UninstallerFileName = "XXAR-Uninstall.exe";
        public const string LauncherFileName = "XXAR.exe";
        public const string ShortcutFileName = "XXAR.lnk";
        public const string PayloadFolderName = "resources";

        // Machine-local data the app writes itself; the installer never ships any of it.
        public static readonly string[] RuntimeDataFolders = { "tools", "cache", "state", "updates", "logs" };

        public static string DefaultRoot =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), ProductName);

        public static string UserDataRoot =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), ProductName);

        public static string StartMenuFolder =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                         @"Microsoft\Windows\Start Menu\Programs\" + ProductName);

        public static string PayloadFolderIn(string root) => Path.Combine(root, PayloadFolderName);

        public static string LauncherIn(string root) => Path.Combine(root, PayloadFolderName, LauncherFileName);

        public static string UninstallerIn(string root) => Path.Combine(root, UninstallerFileName);

        // Child processes are launched by absolute path so a binary planted next to the downloaded
        // installer can never be picked up ahead of the real system one.
        public static string SystemExecutable(string fileName)
            => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), fileName);
    }
}
