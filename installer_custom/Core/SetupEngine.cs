using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Threading;
using Microsoft.Win32;

namespace XXAR.Setup
{
    public class AppRunningException : Exception { }

    // All filesystem/registry work, UI-free so the silent paths reuse it verbatim.
    public static class SetupEngine
    {
        private const string UninstallKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\XXAR";

        // Shipped inside the payload and extracted like any other file.
        private const string UninstallerName = "XXAR-Uninstall.exe";

        // Child processes are always launched by absolute path,
        // a binary planted next to the downloaded setup can never be picked up ahead of the real system one.
        private static string SystemExe(string fileName)
            => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), fileName);

        public static void Install(SetupContext ctx, IProgress<(int pct, string status)> progress, CancellationToken ct)
        {
            ThrowIfAppRunning(ctx.TargetDir);
            RemoveMsiInstall(progress);

            var app = ctx.TargetDir;
            var staging = Path.Combine(app, ".xxar-staging");
            Directory.CreateDirectory(app);
            if (Directory.Exists(staging)) Directory.Delete(staging, true);

            try
            {
                progress?.Report((0, "Extracting files..."));
                ExtractPayload(ctx, staging, progress, ct);

                // The old tree is replaced only after a fully successful extraction, so a failed run never leaves a half install.
                progress?.Report((92, "Installing files..."));
                foreach (var stagedDir in Directory.GetDirectories(staging))
                {
                    var final = Path.Combine(app, Path.GetFileName(stagedDir));
                    if (Directory.Exists(final)) Directory.Delete(final, true);
                    Directory.Move(stagedDir, final);
                }
                foreach (var stagedFile in Directory.GetFiles(staging))
                {
                    var final = Path.Combine(app, Path.GetFileName(stagedFile));
                    if (File.Exists(final)) File.Delete(final);
                    File.Move(stagedFile, final);
                }
                Directory.Delete(staging, true);

                progress?.Report((95, "Creating shortcuts..."));
                WriteRegistry(ctx, app);
                WriteShortcuts(app);
                progress?.Report((100, "Done"));
                SetupLog.Info($"installed to {app}");
            }
            catch
            {
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
                throw;
            }
        }

        private static void ExtractPayload(SetupContext ctx, string staging,
            IProgress<(int pct, string status)> progress, CancellationToken ct)
        {
            var stagingRoot = Path.GetFullPath(staging);
            if (!stagingRoot.EndsWith(Path.DirectorySeparatorChar.ToString()))
                stagingRoot += Path.DirectorySeparatorChar;

            using (var zip = PayloadReader.OpenPayload(ctx.ExePath, ctx.Payload.ZipOffset))
            {
                var entries = zip.Entries;
                int done = 0, rejected = 0;
                foreach (var entry in entries)
                {
                    ct.ThrowIfCancellationRequested();

                    string dest;
                    try { dest = Path.GetFullPath(Path.Combine(staging, entry.FullName)); }
                    catch { rejected++; continue; }

                    // The payload is our own build, but a rooted or ..\ entry must never write outside staging.
                    // The trailing separator matters: without it "...\XXARevil" would pass a plain prefix test.
                    if (!dest.StartsWith(stagingRoot, StringComparison.OrdinalIgnoreCase))
                    {
                        rejected++;
                        continue;
                    }

                    // A zero-length Name is how a zip marks a directory entry, whatever separator it used.
                    if (entry.Name.Length == 0)
                    {
                        Directory.CreateDirectory(dest);
                    }
                    else
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(dest));
                        entry.ExtractToFile(dest, overwrite: true);
                    }

                    done++;
                    if (done % 25 == 0)
                        progress?.Report((done * 90 / entries.Count, entry.Name));
                }
                if (rejected > 0)
                    SetupLog.Error($"{rejected} payload entries rejected for pointing outside the staging folder");
            }
        }

        public static void Uninstall(SetupContext ctx, bool purgeUserData, IProgress<(int pct, string status)> progress)
        {
            var app = (ctx.InstalledLocation ?? Path.GetDirectoryName(ctx.ExePath)).TrimEnd('\\');
            ThrowIfAppRunning(app);

            progress?.Report((10, "Removing application files..."));
            DeleteTree(Path.Combine(app, "resources"));

            // Whatever else the payload dropped at the install root, such as the version marker, goes too.
            // The uninstaller running right now is the one exception; it is parked at the end instead.
            foreach (var file in SafeGetFiles(app))
            {
                if (string.Equals(file, ctx.ExePath, StringComparison.OrdinalIgnoreCase)) continue;
                try { File.Delete(file); }
                catch (Exception ex) { SetupLog.Error($"delete failed for {file}", ex); }
            }

            // Machine-local runtime data the installer never shipped: tools, caches, state, logs.
            progress?.Report((40, "Removing downloaded tools and caches..."));
            var localData = SetupContext.DefaultInstallDir;
            foreach (var sub in new[] { "tools", "cache", "state", "updates", "logs" })
                DeleteTree(Path.Combine(localData, sub));

            if (purgeUserData)
            {
                progress?.Report((60, "Removing mods and settings..."));
                DeleteTree(Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "XXAR"));
            }

            progress?.Report((80, "Removing shortcuts and registry entries..."));
            DeleteTree(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                @"Microsoft\Windows\Start Menu\Programs\XXAR"));
            try { Registry.CurrentUser.DeleteSubKeyTree(UninstallKeyPath, false); } catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(@"Software\XXAR", false); } catch { }

            if (ctx.ExePath.StartsWith(app, StringComparison.OrdinalIgnoreCase))
                ParkSelfForCleanup(ctx.ExePath, app);
            else
                DeleteTree(app);

            progress?.Report((100, "Done"));
            SetupLog.Info($"uninstalled from {app} (purge={purgeUserData})");
        }

        // A leftover per-user MSI install is removed through msiexec; UPGRADINGPRODUCTCODE suppresses its
        // CleanupXXARData action (same as a real MSI major upgrade), so downloaded tools survive the migration.
        public static void RemoveMsiInstall(IProgress<(int pct, string status)> progress)
        {
            foreach (var productCode in FindMsiProductCodes())
            {
                progress?.Report((0, "Removing previous version..."));
                SetupLog.Info($"removing MSI product {productCode}");
                var psi = new ProcessStartInfo
                {
                    FileName = SystemExe("msiexec.exe"),
                    Arguments = $"/x {productCode} /qn UPGRADINGPRODUCTCODE=1",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                using (var proc = Process.Start(psi))
                {
                    proc.WaitForExit();
                    SetupLog.Info($"msiexec exit {proc.ExitCode}");
                }
            }
        }

        // A per-user MSI can register its uninstall entry under either hive, so all three roots are scanned.
        private static List<string> FindMsiProductCodes()
        {
            var roots = new[]
            {
                new { Hive = Registry.CurrentUser, Path = @"Software\Microsoft\Windows\CurrentVersion\Uninstall" },
                new { Hive = Registry.LocalMachine, Path = @"Software\Microsoft\Windows\CurrentVersion\Uninstall" },
                new { Hive = Registry.LocalMachine, Path = @"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" },
            };

            var codes = new List<string>();
            foreach (var root in roots)
            {
                using (var key = root.Hive.OpenSubKey(root.Path))
                {
                    if (key == null) continue;
                    foreach (var name in key.GetSubKeyNames())
                    {
                        if (!name.StartsWith("{") || !name.EndsWith("}")) continue;
                        using (var entry = key.OpenSubKey(name))
                        {
                            if (entry == null) continue;
                            if (!string.Equals(entry.GetValue("DisplayName") as string, "XXAR", StringComparison.OrdinalIgnoreCase))
                                continue;
                            var uninstallString = entry.GetValue("UninstallString") as string ?? "";
                            if (uninstallString.IndexOf("msiexec", StringComparison.OrdinalIgnoreCase) < 0) continue;
                            if (!codes.Contains(name, StringComparer.OrdinalIgnoreCase)) codes.Add(name);
                        }
                    }
                }
            }
            return codes;
        }

        // Windows keeps a running executable's image locked, so failing to open it for writing is the
        // exact question being asked: can this install be replaced right now.
        public static bool IsAppRunning(string app)
        {
            var exe = Path.Combine(app, "resources", "XXAR.exe");
            if (!File.Exists(exe)) return false;
            try
            {
                using (File.Open(exe, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) return false;
            }
            catch (IOException) { return true; }
            catch (UnauthorizedAccessException) { return true; }
        }

        private static void ThrowIfAppRunning(string app)
        {
            if (IsAppRunning(app)) throw new AppRunningException();
        }

        private static void WriteRegistry(SetupContext ctx, string app)
        {
            var location = app.TrimEnd('\\') + "\\";
            using (var key = Registry.CurrentUser.CreateSubKey(@"Software\XXAR"))
            {
                key.SetValue("InstallLocation", location);
                key.SetValue("Version", ctx.PayloadVersion);
                // Read by the app's updater to pick the .exe update channel instead of the retired MSI one.
                key.SetValue("InstallerKind", "exe");
            }

            long bytes = new DirectoryInfo(Path.Combine(app, "resources"))
                .EnumerateFiles("*", SearchOption.AllDirectories).Sum(f => f.Length);
            using (var key = Registry.CurrentUser.CreateSubKey(UninstallKeyPath))
            {
                key.SetValue("DisplayName", "XXAR");
                key.SetValue("DisplayVersion", ctx.PayloadVersion);
                key.SetValue("Publisher", "Entity378");
                key.SetValue("InstallLocation", location);
                key.SetValue("DisplayIcon", Path.Combine(app, "resources", "XXAR.exe"));
                key.SetValue("UninstallString", $"\"{Path.Combine(app, UninstallerName)}\"");
                key.SetValue("QuietUninstallString", $"\"{Path.Combine(app, UninstallerName)}\" /uninstall /silent");
                key.SetValue("URLInfoAbout", "https://github.com/Entity378/XXAR");
                key.SetValue("HelpLink", "https://github.com/Entity378/XXAR");
                key.SetValue("EstimatedSize", (int)(bytes / 1024), RegistryValueKind.DWord);
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }

        private static void WriteShortcuts(string app)
        {
            var exe = Path.Combine(app, "resources", "XXAR.exe");
            var workingDir = Path.Combine(app, "resources");
            const string description = "Cross-game Audio Replacer";

            var startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                @"Microsoft\Windows\Start Menu\Programs\XXAR");
            Directory.CreateDirectory(startMenu);

            ShellShortcut.Create(Path.Combine(startMenu, "XXAR.lnk"), exe, workingDir, description);
            ShellShortcut.Create(Path.Combine(app, "XXAR.lnk"), exe, workingDir, description);
        }

        // Windows will not delete a running image, and a per-user installer cannot register a delete-at-reboot because that list lives under HKLM.
        // Renaming the file out of the way empties the install folder now.
        private static void ParkSelfForCleanup(string exePath, string appDir)
        {
            try
            {
                var tempDir = Path.GetTempPath();
                var parkedName = "XXAR-Uninstall-" + Guid.NewGuid().ToString("N") + ".tmp";
                // A cross-volume move copies then deletes, and deleting a running image fails, so stay put instead.
                bool sameVolume = string.Equals(Path.GetPathRoot(tempDir), Path.GetPathRoot(exePath),
                                                StringComparison.OrdinalIgnoreCase);
                var parked = sameVolume
                    ? Path.Combine(tempDir, parkedName)
                    : Path.Combine(Path.GetDirectoryName(exePath), parkedName);

                File.Move(exePath, parked);
                try { Directory.Delete(appDir); } catch { }
            }
            catch (Exception ex)
            {
                SetupLog.Error("could not park the uninstaller for cleanup", ex);
            }
        }

        private static string[] SafeGetFiles(string path)
        {
            try { return Directory.Exists(path) ? Directory.GetFiles(path) : new string[0]; }
            catch { return new string[0]; }
        }

        private static void DeleteTree(string path)
        {
            try
            {
                if (Directory.Exists(path)) Directory.Delete(path, true);
            }
            catch (Exception ex)
            {
                SetupLog.Error($"delete failed for {path}", ex);
            }
        }
    }
}
