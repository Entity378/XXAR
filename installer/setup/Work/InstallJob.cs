using System;
using System.IO;
using System.IO.Compression;
using System.Threading;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // Unpacks the payload and registers the install. UI-free, so the silent path runs it verbatim.
    public static class InstallJob
    {
        private const string StagingFolderName = ".xxar-staging";

        public static void Run(SetupSession session, IProgress<StepProgress> progress, CancellationToken cancel)
        {
            var root = session.TargetRoot;
            AppLock.ThrowIfRunning(InstallLocations.LauncherIn(root));
            LegacyMsi.RemoveIfPresent(progress);

            var staging = Path.Combine(root, StagingFolderName);
            Directory.CreateDirectory(root);
            Disk.DeleteTree(staging);

            try
            {
                progress?.Report(new StepProgress(0, "Extracting files..."));
                Unpack(session.Machine, staging, progress, cancel);

                // The old tree is replaced only once extraction has fully succeeded, so a failed run
                // never leaves a half install behind.
                progress?.Report(new StepProgress(92, "Installing files..."));
                PromoteStaging(staging, root);

                progress?.Report(new StepProgress(95, "Creating shortcuts..."));
                InstallRecord.Publish(root, session.Machine.OfferedVersion);
                CreateShortcuts(root);

                progress?.Report(new StepProgress(100, "Done"));
                Journal.Info($"installed to {root}");
            }
            catch
            {
                Disk.DeleteTree(staging);
                throw;
            }
        }

        private static void Unpack(MachineState machine, string staging,
                                   IProgress<StepProgress> progress, CancellationToken cancel)
        {
            var stagingPrefix = Path.GetFullPath(staging).TrimEnd(Path.DirectorySeparatorChar)
                                + Path.DirectorySeparatorChar;

            using (var archive = SelfExtract.OpenArchive(machine.ExecutablePath, machine.ArchiveOffset))
            {
                var entries = archive.Entries;
                int written = 0, rejected = 0;

                foreach (var entry in entries)
                {
                    cancel.ThrowIfCancellationRequested();

                    var destination = ResolveInside(stagingPrefix, staging, entry.FullName);
                    if (destination == null)
                    {
                        rejected++;
                        continue;
                    }

                    // A zero-length Name is how an archive marks a directory, whatever separator it used.
                    if (entry.Name.Length == 0)
                    {
                        Directory.CreateDirectory(destination);
                    }
                    else
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(destination));
                        entry.ExtractToFile(destination, overwrite: true);
                    }

                    written++;
                    if (written % 25 == 0)
                        progress?.Report(new StepProgress(written * 90 / entries.Count, entry.Name));
                }

                if (rejected > 0)
                    Journal.Error($"{rejected} payload entries rejected for pointing outside the staging folder");
            }
        }

        // The payload is our own build, but a rooted or ..\ entry must never write outside staging.
        // The trailing separator on the prefix matters: without it "...\XXARevil" would pass the test.
        private static string ResolveInside(string stagingPrefix, string staging, string entryPath)
        {
            try
            {
                var full = Path.GetFullPath(Path.Combine(staging, entryPath));
                return full.StartsWith(stagingPrefix, StringComparison.OrdinalIgnoreCase) ? full : null;
            }
            catch
            {
                return null;
            }
        }

        private static void PromoteStaging(string staging, string root)
        {
            foreach (var stagedFolder in Directory.GetDirectories(staging))
            {
                var destination = Path.Combine(root, Path.GetFileName(stagedFolder));
                if (Directory.Exists(destination)) Directory.Delete(destination, recursive: true);
                Directory.Move(stagedFolder, destination);
            }

            foreach (var stagedFile in Directory.GetFiles(staging))
            {
                var destination = Path.Combine(root, Path.GetFileName(stagedFile));
                if (File.Exists(destination)) File.Delete(destination);
                File.Move(stagedFile, destination);
            }

            Directory.Delete(staging, recursive: true);
        }

        private static void CreateShortcuts(string root)
        {
            var launcher = InstallLocations.LauncherIn(root);
            var workingFolder = InstallLocations.PayloadFolderIn(root);
            const string description = "Cross-game Audio Replacer";

            Directory.CreateDirectory(InstallLocations.StartMenuFolder);
            Shortcut.Write(Path.Combine(InstallLocations.StartMenuFolder, InstallLocations.ShortcutFileName),
                           launcher, workingFolder, description);
            Shortcut.Write(Path.Combine(root, InstallLocations.ShortcutFileName),
                           launcher, workingFolder, description);
        }
    }
}
