using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.Win32;
using XXAR.Wizard;

namespace XXAR.Uninstall
{
    // One removable group of folders, shown to the user with the space it takes.
    // Properties rather than fields because the options step binds to them, and WPF ignores fields.
    public class RemovalGroup
    {
        public string Title { get; set; }
        public string Detail { get; set; }
        public List<string> Folders { get; } = new List<string>();
        public long Bytes { get; set; }
        public bool Selected { get; set; } = true;
        public bool Required { get; set; }

        public string SizeText { get { return Sizes.Describe(Bytes); } }
        // The application itself is not optional, so its checkbox stays ticked and disabled.
        public bool CanDeselect { get { return !Required; } }
    }

    // What is installed, where, and how much of it there is. Built once at startup so the options
    // step can show real numbers instead of asking the user to guess what "caches" means.
    public class RemovalPlan
    {
        public string InstalledRoot { get; private set; }
        public string InstalledVersion { get; private set; }
        public string FailureText { get; set; }

        public RemovalGroup Application { get; private set; }
        public RemovalGroup Tools { get; private set; }
        public RemovalGroup UserData { get; private set; }

        public bool IsInstalled { get { return InstalledRoot != null; } }

        public IEnumerable<RemovalGroup> Groups
        {
            get
            {
                yield return Application;
                yield return Tools;
                yield return UserData;
            }
        }

        public long SelectedBytes { get { return Groups.Where(g => g.Selected).Sum(g => g.Bytes); } }

        public static RemovalPlan Build()
        {
            var plan = new RemovalPlan();
            plan.Locate();
            plan.Describe();

            foreach (var group in plan.Groups)
                group.Bytes = group.Folders.Sum(Disk.SizeOf);

            Journal.Info($"install={plan.InstalledRoot ?? "not found"} version={plan.InstalledVersion ?? "?"} " +
                         $"app={Sizes.Describe(plan.Application.Bytes)} tools={Sizes.Describe(plan.Tools.Bytes)} " +
                         $"userdata={Sizes.Describe(plan.UserData.Bytes)}");
            return plan;
        }

        private void Locate()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(RemovalLocations.ProductKey))
            {
                var root = key?.GetValue("InstallLocation") as string;
                if (!string.IsNullOrEmpty(root) && Directory.Exists(root))
                {
                    InstalledRoot = root.TrimEnd('\\');
                    InstalledVersion = key.GetValue("Version") as string;
                }
            }

            // Falling back to the folder we sit in keeps the uninstaller usable if the registry entry
            // was lost, which is the state a half-finished install leaves behind.
            if (InstalledRoot != null) return;

            var here = Path.GetDirectoryName(
                System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName);
            if (Directory.Exists(RemovalLocations.PayloadFolderIn(here)))
                InstalledRoot = here.TrimEnd('\\');
        }

        private void Describe()
        {
            Application = new RemovalGroup
            {
                Title = "XXAR",
                Detail = "The application itself and its shortcut.",
                Required = true,
            };
            if (InstalledRoot != null)
                Application.Folders.Add(RemovalLocations.PayloadFolderIn(InstalledRoot));

            Tools = new RemovalGroup
            {
                Title = "Downloaded tools and caches",
                Detail = "Wwise, FFmpeg and vgmstream, plus caches and logs. They are downloaded again on demand.",
            };
            foreach (var folder in RemovalLocations.RuntimeDataFolders)
                Tools.Folders.Add(Path.Combine(RemovalLocations.LocalDataRoot, folder));

            UserData = new RemovalGroup
            {
                Title = "Mods and settings",
                Detail = "Your mod library and configuration. Leave unchecked to keep them for a future reinstall.",
                Selected = false,
            };
            UserData.Folders.Add(RemovalLocations.UserDataRoot);
        }
    }
}
