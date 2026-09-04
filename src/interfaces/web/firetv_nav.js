/**
 * Fire TV & Vega OS 10-Foot Leanback Spatial D-Pad Navigation & Incident Room Controller.
 * Handles remote control keycodes: DPAD_UP (38), DPAD_DOWN (40), DPAD_LEFT (37), DPAD_RIGHT (39), ENTER/SELECT (13).
 * Exposes window.navigateDpad(direction) for native Android Leanback MainActivity.kt bridge.
 */

class FireTVSpatialNavigator {
    constructor() {
        this.focusableElements = [];
        this.currentIndex = 0;
        this.pairingCode = this.generatePairingCode();
        this.init();
    }

    generatePairingCode() {
        const rand = Math.floor(1000 + Math.random() * 9000);
        return `TV-${rand}`;
    }

    init() {
        document.addEventListener('keydown', (e) => this.handleKeyDown(e));
        window.addEventListener('DOMContentLoaded', () => {
            this.refreshFocusableElements();
            this.injectPairingBadge();
        });
    }

    refreshFocusableElements() {
        this.focusableElements = Array.from(document.querySelectorAll('.tv-nav, .btn, .nav-btn, .focusable, a, button, input'));
        if (this.focusableElements.length > 0) {
            this.focusElement(0);
        }
    }

    focusElement(index) {
        if (this.focusableElements.length === 0) return;
        this.focusableElements.forEach(el => el.classList.remove('dpad-focused'));
        this.currentIndex = (index + this.focusableElements.length) % this.focusableElements.length;
        const current = this.focusableElements[this.currentIndex];
        if (current) {
            current.classList.add('dpad-focused');
            current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            current.focus();
        }
    }

    handleKeyDown(e) {
        switch(e.key) {
            case 'ArrowDown':
            case 'Down':
                e.preventDefault();
                this.focusElement(this.currentIndex + 1);
                break;
            case 'ArrowUp':
            case 'Up':
                e.preventDefault();
                this.focusElement(this.currentIndex - 1);
                break;
            case 'ArrowRight':
            case 'Right':
                e.preventDefault();
                this.focusElement(this.currentIndex + 1);
                break;
            case 'ArrowLeft':
            case 'Left':
                e.preventDefault();
                this.focusElement(this.currentIndex - 1);
                break;
            case 'Enter':
            case 'Select':
                if (this.focusableElements[this.currentIndex]) {
                    this.focusableElements[this.currentIndex].click();
                }
                break;
        }
    }

    injectPairingBadge() {
        const el = document.getElementById('firetv-pairing-badge');
        if (el) {
            el.innerHTML = `📺 Fire TV Incident Cockpit: <strong>${this.pairingCode}</strong> <span style="color:#00e676;">● Active</span>`;
        }
    }
}

window.fireTVNav = new FireTVSpatialNavigator();

// Native Android Leanback / Fire OS MainActivity.kt Bridge
window.navigateDpad = function(direction) {
    if (!window.fireTVNav) return;
    const nav = window.fireTVNav;
    switch(direction) {
        case 'UP':
            nav.focusElement(nav.currentIndex - 1);
            break;
        case 'DOWN':
            nav.focusElement(nav.currentIndex + 1);
            break;
        case 'LEFT':
            nav.focusElement(nav.currentIndex - 1);
            break;
        case 'RIGHT':
            nav.focusElement(nav.currentIndex + 1);
            break;
        case 'SELECT':
            if (nav.focusableElements[nav.currentIndex]) {
                nav.focusableElements[nav.currentIndex].click();
            }
            break;
    }
};
