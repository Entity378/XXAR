using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // The in-app updater's side of an install: wait for the app to let go of its files, then start it again.
    public static class UpdateHandoff
    {
        // The app's updater launches us and only then quits, so its files are still locked for a moment.
        private static readonly TimeSpan ShutdownGrace = TimeSpan.FromSeconds(60);

        public static void WaitForAppToClose(string installedRoot)
        {
            if (installedRoot == null) return;

            var launcher = InstallLocations.LauncherIn(installedRoot);
            var giveUpAt = DateTime.UtcNow + ShutdownGrace;
            if (!AppLock.IsRunning(launcher)) return;

            Journal.Info("waiting for XXAR to close");
            while (AppLock.IsRunning(launcher) && DateTime.UtcNow < giveUpAt)
                Thread.Sleep(500);

            // Still locked means the job below throws AppRunningException, which the caller logs.
            Journal.Info(AppLock.IsRunning(launcher) ? "XXAR is still running" : "XXAR closed");
        }

        public static void Relaunch(string root)
        {
            var payloadFolder = InstallLocations.PayloadFolderIn(root);
            var start = new ProcessStartInfo(InstallLocations.LauncherIn(root))
            {
                WorkingDirectory = payloadFolder,
                UseShellExecute = false,
            };

            // Our environment is the old app's: its PyInstaller variables would make the new one start as its child.
            foreach (var name in start.Environment.Keys.Where(IsFrozenAppVariable).ToList())
                start.Environment.Remove(name);
            if (start.Environment.TryGetValue("PATH", out var path))
                start.Environment["PATH"] = WithoutFolder(path, payloadFolder);

            try
            {
                Process.Start(start);
                Journal.Info("restarted XXAR");
            }
            catch (Exception ex)
            {
                Journal.Error("could not restart XXAR", ex);
            }
        }

        private static bool IsFrozenAppVariable(string name)
        {
            return name.StartsWith("_PYI_", StringComparison.OrdinalIgnoreCase)
                   || name.StartsWith("_MEIPASS", StringComparison.OrdinalIgnoreCase);
        }

        private static string WithoutFolder(string pathVariable, string folder)
        {
            var prefix = folder.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var kept = pathVariable.Split(Path.PathSeparator)
                .Where(entry => !(entry.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar)
                    .StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
            return string.Join(Path.PathSeparator.ToString(), kept);
        }
    }
}
