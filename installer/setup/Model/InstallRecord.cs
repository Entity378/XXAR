using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.Win32;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // Everything the installer publishes to, or reads back from, the registry.
    public static class InstallRecord
    {
        private const string ProductKey = @"Software\XXAR";
        private const string ArpKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\XXAR";
        private const string ProjectUrl = "https://github.com/Entity378/XXAR";

        // Null when nothing is installed, or when the recorded folder no longer holds the launcher.
        public static string ReadInstalledRoot()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(ProductKey))
            {
                var root = key?.GetValue("InstallLocation") as string;
                if (string.IsNullOrEmpty(root)) return null;
                root = root.TrimEnd('\\');
                return File.Exists(InstallLocations.LauncherIn(root)) ? root : null;
            }
        }

        public static string ReadInstalledVersion()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(ProductKey))
                return key?.GetValue("Version") as string;
        }

        public static void Publish(string root, string version)
        {
            var location = root.TrimEnd('\\') + "\\";

            using (var key = Registry.CurrentUser.CreateSubKey(ProductKey))
            {
                key.SetValue("InstallLocation", location);
                key.SetValue("Version", version);
                // Read by the app's updater to pick the .exe update channel instead of the retired MSI one.
                key.SetValue("InstallerKind", "exe");
            }

            long installedBytes = new DirectoryInfo(InstallLocations.PayloadFolderIn(root))
                .EnumerateFiles("*", SearchOption.AllDirectories).Sum(f => f.Length);
            var uninstaller = InstallLocations.UninstallerIn(root);

            using (var key = Registry.CurrentUser.CreateSubKey(ArpKey))
            {
                key.SetValue("DisplayName", InstallLocations.ProductName);
                key.SetValue("DisplayVersion", version);
                key.SetValue("Publisher", "Entity378");
                key.SetValue("InstallLocation", location);
                key.SetValue("DisplayIcon", InstallLocations.LauncherIn(root));
                key.SetValue("UninstallString", $"\"{uninstaller}\"");
                key.SetValue("QuietUninstallString", $"\"{uninstaller}\" /uninstall /silent");
                key.SetValue("URLInfoAbout", ProjectUrl);
                key.SetValue("HelpLink", ProjectUrl);
                key.SetValue("EstimatedSize", (int)(installedBytes / 1024), RegistryValueKind.DWord);
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }

        public static void Withdraw()
        {
            DeleteKeyTree(ArpKey);
            DeleteKeyTree(ProductKey);
        }

        private static void DeleteKeyTree(string path)
        {
            try { Registry.CurrentUser.DeleteSubKeyTree(path, throwOnMissingSubKey: false); }
            catch (Exception ex) { Journal.Error($"could not remove {path}", ex); }
        }

        // Product codes of any per-user MSI install of XXAR still registered on this machine.
        // A per-user package can land under either hive, so all three roots are scanned.
        public static List<string> FindMsiProductCodes()
        {
            var roots = new (RegistryKey Hive, string Path)[]
            {
                (Registry.CurrentUser,  @"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (Registry.LocalMachine, @"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (Registry.LocalMachine, @"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            };

            var productCodes = new List<string>();
            foreach (var root in roots)
            {
                using (var key = root.Hive.OpenSubKey(root.Path))
                {
                    if (key == null) continue;
                    foreach (var name in key.GetSubKeyNames())
                    {
                        if (!name.StartsWith("{") || !name.EndsWith("}")) continue;
                        if (productCodes.Contains(name, StringComparer.OrdinalIgnoreCase)) continue;
                        if (IsXxarMsiEntry(key, name)) productCodes.Add(name);
                    }
                }
            }
            return productCodes;
        }

        private static bool IsXxarMsiEntry(RegistryKey uninstallRoot, string subKeyName)
        {
            using (var entry = uninstallRoot.OpenSubKey(subKeyName))
            {
                if (entry == null) return false;
                if (!string.Equals(entry.GetValue("DisplayName") as string,
                                   InstallLocations.ProductName, StringComparison.OrdinalIgnoreCase))
                    return false;

                var uninstallString = entry.GetValue("UninstallString") as string ?? "";
                return uninstallString.IndexOf("msiexec", StringComparison.OrdinalIgnoreCase) >= 0;
            }
        }
    }
}
