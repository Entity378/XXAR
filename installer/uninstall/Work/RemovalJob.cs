using System;
using System.IO;
using System.Linq;
using Microsoft.Win32;
using XXAR.Wizard;

namespace XXAR.Uninstall
{
    // The removal itself, UI-free so the silent path runs it verbatim.
    public static class RemovalJob
    {
        public static void Run(RemovalPlan plan, IProgress<StepProgress> progress)
        {
            if (plan.InstalledRoot != null)
                AppLock.ThrowIfRunning(RemovalLocations.LauncherIn(plan.InstalledRoot));

            var chosen = plan.Groups.Where(group => group.Selected).ToList();
            for (int done = 0; done < chosen.Count; done++)
            {
                var group = chosen[done];
                progress?.Report(new StepProgress(done * 70 / Math.Max(1, chosen.Count),
                                                  $"Removing {group.Title.ToLowerInvariant()}..."));
                foreach (var folder in group.Folders)
                    Disk.DeleteTree(folder);
            }

            progress?.Report(new StepProgress(75, "Removing shortcuts..."));
            Disk.DeleteTree(RemovalLocations.StartMenuFolder);

            progress?.Report(new StepProgress(85, "Removing registry entries..."));
            WithdrawRegistry();

            progress?.Report(new StepProgress(95, "Cleaning up..."));
            RemoveLeftovers(plan);

            progress?.Report(new StepProgress(100, "Done"));
            Journal.Info($"removed: {string.Join(", ", chosen.Select(group => group.Title))}");
        }

        private static void WithdrawRegistry()
        {
            foreach (var path in new[] { RemovalLocations.ArpKey, RemovalLocations.ProductKey })
            {
                try { Registry.CurrentUser.DeleteSubKeyTree(path, throwOnMissingSubKey: false); }
                catch (Exception ex) { Journal.Error($"could not remove {path}", ex); }
            }
        }

        // Anything left at the install root, plus the folder itself. The running uninstaller is the
        // one file that cannot be deleted, so it is renamed out of the way instead.
        private static void RemoveLeftovers(RemovalPlan plan)
        {
            if (plan.InstalledRoot == null) return;
            var self = System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName;

            foreach (var file in Disk.FilesIn(plan.InstalledRoot))
            {
                if (string.Equals(file, self, StringComparison.OrdinalIgnoreCase)) continue;
                Disk.DeleteFile(file);
            }
            foreach (var folder in Disk.FoldersIn(plan.InstalledRoot))
                Disk.DeleteTree(folder);

            // The local data folder may survive as an empty shell once its subfolders are gone.
            Disk.DeleteIfEmpty(RemovalLocations.LocalDataRoot);

            if (self.StartsWith(plan.InstalledRoot, StringComparison.OrdinalIgnoreCase))
                Disk.MoveOutOfTheWay(self);

            Disk.DeleteIfEmpty(plan.InstalledRoot);
        }
    }
}
