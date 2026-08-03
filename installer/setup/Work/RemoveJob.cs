using System;
using System.IO;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // Takes the install apart in the reverse order it was built. UI-free, like InstallJob.
    public static class RemoveJob
    {
        public static void Run(SetupSession session, IProgress<StepProgress> progress)
        {
            var machine = session.Machine;
            var root = (machine.InstalledRoot ?? Path.GetDirectoryName(machine.ExecutablePath)).TrimEnd('\\');
            AppLock.ThrowIfRunning(InstallLocations.LauncherIn(root));

            progress?.Report(new StepProgress(10, "Removing application files..."));
            Disk.DeleteTree(InstallLocations.PayloadFolderIn(root));
            RemoveLooseFiles(root, machine.ExecutablePath);

            progress?.Report(new StepProgress(40, "Removing downloaded tools and caches..."));
            foreach (var folder in InstallLocations.RuntimeDataFolders)
                Disk.DeleteTree(Path.Combine(InstallLocations.DefaultRoot, folder));

            if (session.PurgeUserData)
            {
                progress?.Report(new StepProgress(60, "Removing mods and settings..."));
                Disk.DeleteTree(InstallLocations.UserDataRoot);
            }

            progress?.Report(new StepProgress(80, "Removing shortcuts and registry entries..."));
            Disk.DeleteTree(InstallLocations.StartMenuFolder);
            InstallRecord.Withdraw();

            RemoveInstallFolder(root, machine.ExecutablePath);

            progress?.Report(new StepProgress(100, "Done"));
            Journal.Info($"uninstalled from {root} (purge={session.PurgeUserData})");
        }

        // Whatever else the payload dropped at the install root, such as the shortcut, goes too.
        // The executable running right now is the one exception; it is dealt with last.
        private static void RemoveLooseFiles(string root, string selfPath)
        {
            foreach (var file in Disk.FilesIn(root))
            {
                if (string.Equals(file, selfPath, StringComparison.OrdinalIgnoreCase)) continue;
                Disk.DeleteFile(file);
            }
        }

        private static void RemoveInstallFolder(string root, string selfPath)
        {
            if (selfPath.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                Disk.MoveOutOfTheWay(selfPath);
                Disk.DeleteIfEmpty(root);
            }
            else
            {
                Disk.DeleteTree(root);
            }
        }
    }
}
