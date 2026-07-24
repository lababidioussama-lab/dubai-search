export interface SearchableUnit {
  id: string;
  tierLabel: string;
  verified: boolean;
}

export interface SearchHandlers {
  onSelect(id: string): void;
  onClear(): void;
}

const MAX_RESULTS = 8;

export class SearchController {
  private input: HTMLInputElement;
  private statusEl: HTMLElement;
  private resultsEl: HTMLElement;
  private units: SearchableUnit[];
  private handlers: SearchHandlers;
  private activeIndex = -1;
  private currentMatches: SearchableUnit[] = [];

  constructor(root: HTMLElement, units: SearchableUnit[], handlers: SearchHandlers) {
    this.input = root.querySelector('#search-input')!;
    this.statusEl = root.querySelector('#search-status')!;
    this.resultsEl = root.querySelector('#search-results')!;
    this.units = units;
    this.handlers = handlers;

    this.input.addEventListener('input', () => this.onInput());
    this.input.addEventListener('keydown', (e) => this.onKeyDown(e));
  }

  private onInput() {
    const query = this.input.value.trim().toUpperCase();
    this.activeIndex = -1;
    this.statusEl.className = '';
    this.statusEl.textContent = '';

    if (!query) {
      this.currentMatches = [];
      this.renderResults();
      return;
    }

    const matches = this.units.filter((u) => u.id.toUpperCase().includes(query));
    this.currentMatches = matches.slice(0, MAX_RESULTS);
    this.renderResults();

    if (matches.length === 0) {
      this.showNotFound(query);
    }
  }

  private onKeyDown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      this.activeIndex = Math.min(this.activeIndex + 1, this.currentMatches.length - 1);
      this.renderResults();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this.activeIndex = Math.max(this.activeIndex - 1, 0);
      this.renderResults();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const query = this.input.value.trim().toUpperCase();
      if (!query) return;

      if (this.activeIndex >= 0 && this.currentMatches[this.activeIndex]) {
        this.select(this.currentMatches[this.activeIndex]);
        return;
      }
      const exact = this.units.find((u) => u.id.toUpperCase() === query);
      if (exact) {
        this.select(exact);
        return;
      }
      if (this.currentMatches.length > 0) {
        this.select(this.currentMatches[0]);
        return;
      }
      this.showNotFound(query);
    } else if (e.key === 'Escape') {
      this.input.value = '';
      this.currentMatches = [];
      this.statusEl.className = '';
      this.statusEl.textContent = '';
      this.renderResults();
      this.handlers.onClear();
    }
  }

  private select(unit: SearchableUnit) {
    this.input.value = unit.id;
    this.currentMatches = [];
    this.renderResults();
    this.statusEl.className = '';
    this.statusEl.textContent = '';

    if (!unit.verified) {
      this.statusEl.className = 'unavailable';
      this.statusEl.textContent = `${unit.id} is in the plot database but its exact location has not been verified yet — location not yet available.`;
      this.handlers.onClear();
      return;
    }
    this.handlers.onSelect(unit.id);
  }

  private showNotFound(query: string) {
    this.statusEl.className = 'not-found';
    this.statusEl.textContent = `"${query}" not found. This preview only covers Portofino's lagoon-frontage villas (BL101–108, BL109–131, BL132–139, BL140–159) — the rest of the community is not yet digitized.`;
    this.handlers.onClear();
  }

  private renderResults() {
    this.resultsEl.innerHTML = '';
    this.currentMatches.forEach((unit, i) => {
      const row = document.createElement('div');
      row.className = 'search-result' + (i === this.activeIndex ? ' active' : '');
      const label = document.createElement('span');
      label.textContent = unit.id;
      const tier = document.createElement('span');
      tier.className = 'plot-tier';
      tier.textContent = unit.verified ? unit.tierLabel : 'location unavailable';
      row.appendChild(label);
      row.appendChild(tier);
      row.addEventListener('click', () => this.select(unit));
      this.resultsEl.appendChild(row);
    });
  }
}
