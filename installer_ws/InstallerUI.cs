using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using WixSharp;
using WixSharp.UI.WPF;
using XXAR.Installer.Dialogs;

namespace XXAR.Installer
{
    // Attaches the WPF ManagedUI and applies the dark theme so no white flashes between dialogs.
    public static class InstallerUI
    {
        // Dark host color (#10123A) used everywhere to avoid white flashes.
        private static readonly Color DarkHostColor = Color.FromArgb(0x10, 0x12, 0x3A);

        // Own AppUserModelID so the installer shows its own taskbar entry, not msiexec's hidden group.
        private const string AppUserModelID = "Entity378.XXAR.Installer";

        private static Icon _cachedIcon;
        private static ITaskbarList _taskbar;

        public static void Attach(ManagedProject project)
        {
            // Set before any window is shown; ignored on failure.
            TrySetAppUserModelID(AppUserModelID);

            project.ManagedUI = new ManagedUI
            {
                InstallDialogs = new ManagedDialogs()
                    .Add<XXARWelcomeDialog>()
                    .Add<XXARLicenceDialog>()
                    .Add<XXARInstallDirDialog>()
                    .Add<XXARProgressDialog>()
                    .Add<XXARExitDialog>(),

                ModifyDialogs = new ManagedDialogs()
                    .Add<XXARMaintenanceTypeDialog>()
                    .Add<XXARProgressDialog>()
                    .Add<XXARExitDialog>(),
            };

            project.UILoaded += OnUILoaded;
        }

        public static void OnUILoaded(SetupEventArgs e)
        {
            if (!(e.ManagedUI is Form shellForm)) return;

            RecolorTree(shellForm);
            EnableImmersiveDarkMode(shellForm.Handle);

            // Force a taskbar entry (msiexec's hidden owner suppresses it).
            ForceTaskbarPresence(shellForm);
            shellForm.Shown += (s, ea) =>
            {
                ForceTaskbarPresence(shellForm);
                TryAddTabToTaskbar(shellForm.Handle);
            };
            shellForm.Activated += (s, ea) => TryAddTabToTaskbar(shellForm.Handle);

            // Recolor each dialog as it's added, before it's painted white.
            shellForm.ControlAdded += (s, ea) =>
            {
                if (ea.Control is Form f)
                {
                    RecolorTree(f);
                    EnableImmersiveDarkMode(f.Handle);
                }
            };

            e.ManagedUI.OnCurrentDialogChanged += dialog =>
            {
                if (dialog is Form dlgForm)
                {
                    RecolorTree(dlgForm);
                    EnableImmersiveDarkMode(dlgForm.Handle);
                }
            };
        }

        private static void ForceTaskbarPresence(Form form)
        {
            form.ShowInTaskbar = true;

            var icon = TryLoadAppIcon();
            if (icon != null) form.Icon = icon;

            // Detach from msiexec's owner window so WS_EX_APPWINDOW is honored.
            SetWindowLongPtrCompat(form.Handle, GWLP_HWNDPARENT, IntPtr.Zero);

            var ex = GetWindowLong(form.Handle, GWL_EXSTYLE);
            var desired = (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW;
            if (desired != ex)
                SetWindowLong(form.Handle, GWL_EXSTYLE, desired);
        }

        private static void TryAddTabToTaskbar(IntPtr hwnd)
        {
            try
            {
                if (_taskbar == null)
                {
                    _taskbar = (ITaskbarList)new CTaskbarList();
                    _taskbar.HrInit();
                }
                _taskbar.AddTab(hwnd);
                _taskbar.ActivateTab(hwnd);
            }
            catch { }
        }

        private static void TrySetAppUserModelID(string id)
        {
            try { SetCurrentProcessExplicitAppUserModelID(id); }
            catch { }
        }

        private static Icon TryLoadAppIcon()
        {
            if (_cachedIcon != null) return _cachedIcon;
            try
            {
                // Icon is an embedded WPF resource; needs a live WPF Application to load.
                if (System.Windows.Application.Current == null) return null;
                var uri = new Uri(
                    "pack://application:,,,/XXAR.Installer.Build;component/Assets/XXAR-Logo2.ico",
                    UriKind.Absolute);
                var info = System.Windows.Application.GetResourceStream(uri);
                if (info?.Stream == null) return null;
                using (info.Stream)
                {
                    _cachedIcon = new Icon(info.Stream);
                    return _cachedIcon;
                }
            }
            catch
            {
                return null;
            }
        }

        private static void RecolorTree(Control c)
        {
            c.BackColor = DarkHostColor;
            foreach (Control child in c.Controls)
                RecolorTree(child);
        }

        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
        private const int GWL_EXSTYLE = -20;
        private const int GWLP_HWNDPARENT = -8;
        private const int WS_EX_APPWINDOW = 0x00040000;
        private const int WS_EX_TOOLWINDOW = 0x00000080;

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int pvAttribute, int cbAttribute);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtr", SetLastError = true)]
        private static extern IntPtr SetWindowLongPtr64(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

        [DllImport("user32.dll", EntryPoint = "SetWindowLong", SetLastError = true)]
        private static extern IntPtr SetWindowLong32(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

        private static IntPtr SetWindowLongPtrCompat(IntPtr hWnd, int nIndex, IntPtr dwNewLong)
        {
            // Pick the right SetWindowLong variant for the process bitness.
            return IntPtr.Size == 8
                ? SetWindowLongPtr64(hWnd, nIndex, dwNewLong)
                : SetWindowLong32(hWnd, nIndex, dwNewLong);
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int SetCurrentProcessExplicitAppUserModelID(
            [MarshalAs(UnmanagedType.LPWStr)] string AppID);

        private static void EnableImmersiveDarkMode(IntPtr hWnd)
        {
            try
            {
                int enable = 1;
                DwmSetWindowAttribute(hWnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref enable, sizeof(int));
            }
            catch { }
        }

        // ITaskbarList COM interop — AddTab force-registers an HWND in the taskbar.
        [ComImport]
        [Guid("56FDF344-FD6D-11D0-958A-006097C9A090")]
        [ClassInterface(ClassInterfaceType.None)]
        private class CTaskbarList { }

        [ComImport]
        [Guid("56FDF342-FD6D-11D0-958A-006097C9A090")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface ITaskbarList
        {
            [PreserveSig] int HrInit();
            [PreserveSig] int AddTab(IntPtr hwnd);
            [PreserveSig] int DeleteTab(IntPtr hwnd);
            [PreserveSig] int ActivateTab(IntPtr hwnd);
            [PreserveSig] int SetActiveAlt(IntPtr hwnd);
        }
    }
}
