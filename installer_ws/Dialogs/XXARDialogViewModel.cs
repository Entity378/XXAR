using System;
using System.ComponentModel;
using System.Drawing;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Windows.Interop;
using WixSharp;
using WixSharp.UI.Forms;

namespace XXAR.Installer.Dialogs
{
    // Shared nav view-model for the WPF dialogs: host, shell, and back/next/cancel.
    public class XXARDialogViewModel : INotifyPropertyChanged
    {
        public ManagedForm Host { get; set; }
        public ISession Session => Host?.Runtime?.Session;
        public IManagedUIShell Shell => Host?.Shell;

        public void GoPrev() => Shell?.GoPrev();
        public void GoNext() => Shell?.GoNext();
        public void Cancel() => Shell?.Cancel();

        public event PropertyChangedEventHandler PropertyChanged;
        protected void OnChanged([CallerMemberName] string name = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    // True when the in-app updater set XXAR_SILENT=1: dialogs auto-advance, only progress shows.
    internal static class XXARSilentUpdate
    {
        // Cached from the first dialog that can read it, because the Exit dialog runs after InstallFinalize.
        // There the session property reads empty, so without the cache it would wait for a manual Finish click.
        private static bool? _cached;

        public static bool IsActive(ManagedForm host)
        {
            if (_cached.HasValue) return _cached.Value;
            try
            {
                var value = host?.Runtime?.Session?.Property("XXAR_SILENT");
                if (!string.IsNullOrEmpty(value))
                {
                    _cached = value == "1";
                    return _cached.Value;
                }
            }
            catch { }
            return false;
        }

        // Skip a dialog, deferred via BeginInvoke rather than synchronously from Init().
        // A synchronous Shell.GoNext()/Exit() reenters the shell and rolls the install back at InstallFinalize (1602).
        public static void SkipTo(System.Windows.Threading.DispatcherObject dialog, System.Action navigate)
            => dialog.Dispatcher.BeginInvoke(navigate, System.Windows.Threading.DispatcherPriority.Background);
    }

    // Paints WinForms host, WPF composition target, and the native HWND dark to avoid white flashes.
    internal static class XXARHostStyling
    {
        private static readonly Color DarkHostColor = Color.FromArgb(0x10, 0x12, 0x3A);
        private static readonly System.Windows.Media.Color DarkWpfColor =
            System.Windows.Media.Color.FromArgb(0xFF, 0x10, 0x12, 0x3A);
        // COLORREF = 0x00BBGGRR
        private const uint HookBrushColorRef = 0x003A1210u;

        private static readonly IntPtr _darkBrush = CreateSolidBrush(HookBrushColorRef);

        public static void ApplyDarkHost(ManagedForm host)
        {
            if (host == null) return;
            host.BackColor = DarkHostColor;
            Recolor(host.Controls);
            for (var p = host.Parent; p != null; p = p.Parent)
                p.BackColor = DarkHostColor;
        }

        public static void RegisterDarkWpfCompositionTarget(System.Windows.Controls.UserControl dialog)
        {
            if (dialog == null) return;
            System.Windows.PresentationSource.AddSourceChangedHandler(dialog, OnSourceChanged);
        }

        private static void OnSourceChanged(object sender, System.Windows.SourceChangedEventArgs e)
        {
            if (!(e.NewSource is HwndSource src)) return;
            if (src.CompositionTarget != null)
                src.CompositionTarget.BackgroundColor = DarkWpfColor;
            src.AddHook(HwndSourceHook);
            // Repaint so the first erase goes through our hook, not the white class brush.
            if (src.Handle != IntPtr.Zero)
                InvalidateRect(src.Handle, IntPtr.Zero, true);
        }

        private static IntPtr HwndSourceHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            const int WM_ERASEBKGND = 0x0014;
            if (msg == WM_ERASEBKGND)
            {
                var rect = new RECT();
                GetClientRect(hwnd, ref rect);
                FillRect(wParam, ref rect, _darkBrush);
                handled = true;
                return (IntPtr)1;
            }
            return IntPtr.Zero;
        }

        private static void Recolor(System.Windows.Forms.Control.ControlCollection controls)
        {
            foreach (System.Windows.Forms.Control c in controls)
            {
                c.BackColor = DarkHostColor;
                if (c.HasChildren) Recolor(c.Controls);
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT { public int L, T, R, B; }

        [DllImport("gdi32.dll")] private static extern IntPtr CreateSolidBrush(uint colorref);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr hWnd, ref RECT r);
        [DllImport("user32.dll")] private static extern int FillRect(IntPtr hdc, ref RECT r, IntPtr hbr);
        [DllImport("user32.dll")] private static extern bool InvalidateRect(IntPtr hWnd, IntPtr lpRect, bool bErase);
    }
}
