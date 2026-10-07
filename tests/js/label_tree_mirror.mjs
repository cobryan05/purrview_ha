/**
 * Runs the card's label-tree helpers and the main app's side by side over one tree,
 * and prints both results as JSON for tests/test_card_label_tree_mirror.py to compare.
 *
 * The two implementations are hand-copies with no build step between them (they live
 * in different repos), so the only thing that can keep them honest is asserting they
 * agree on the same input. Takes the two repo roots as argv.
 */
import { readFileSync } from 'node:fs';

const [cardRepo, appRepo] = process.argv.slice(2);

const CARD = `${cardRepo}/custom_components/purrview/www/purrview-events-card.js`;
const FILTERS = `${appRepo}/apps/image_tagging_server/static/js/app/nvr/events/filters.js`;
const LABEL_LIST = `${appRepo}/apps/image_tagging_server/static/js/ui/labelList.js`;

/** The source between `start` and the next occurrence of `end`. */
function slice(src, start, end) {
  const from = src.indexOf(start);
  if (from < 0) throw new Error(`${start} is gone - the mirror moved, not diverged`);
  const to = src.indexOf(end, from);
  return src.slice(from, to < 0 ? undefined : to);
}

const cardFns = slice(readFileSync(CARD, 'utf8'), 'function labelTreeItems', 'class PurrviewEventsCard');
const appFn = slice(readFileSync(FILTERS, 'utf8'), 'export function labelFacetItems', '\n\n').replace('export ', '');
const listSrc = readFileSync(LABEL_LIST, 'utf8');
const buildHierarchy = slice(listSrc, 'export function buildHierarchy', '\n\n/**').replace('export ', '');
const flattenHierarchy = slice(listSrc, 'export function flattenHierarchy', '\n\n/**').replace('export ', '');
const appExpand = slice(listSrc, 'export function expandWithDescendants', '\n\n//').replace(
  'export function expandWithDescendants',
  'function appExpandWithDescendants'
);

const module = [
  cardFns,
  buildHierarchy,
  flattenHierarchy,
  appFn,
  appExpand,
  'export { labelTreeItems, expandWithDescendants, labelFacetItems, appExpandWithDescendants };',
].join('\n');

const loaded = await import('data:text/javascript;base64,' + Buffer.from(module).toString('base64'));

const label = (uuid, name, parentUuid = null) => [uuid, { uuid, name, parentUuid }];
// Every case the two implementations special-case: a parent nothing ever acted as
// (Vehicle, Bowl - only their children have events), a label whose parent was deleted
// (Orphan), and a ref that is not a label at all (a motion zone).
const labels = new Map([
  label('veh', 'Vehicle'),
  label('focus', 'Focus', 'veh'),
  label('mazda', 'Mazda3', 'veh'),
  label('person', 'Person'),
  label('bowl', 'Bowl'),
  label('bowl-a', 'Bowl A', 'bowl'),
  label('orphan', 'Orphan', 'parent-that-was-deleted'),
]);
const options = [
  { ref: 'focus', name: 'Focus' },
  { ref: 'mazda', name: 'Mazda3' },
  { ref: 'bowl-a', name: 'Bowl A' },
  { ref: 'orphan', name: 'Orphan' },
  { ref: 'zone-7', name: 'Driveway zone' },
];

/** Both sides to one shape: the card says `ref`, the app says `uuid`. */
const rows = (items) =>
  items.map((item) =>
    item.isSeparator
      ? { separator: true }
      : { ref: item.ref ?? item.uuid, name: item.name, depth: item.depth ?? 0 }
  );

console.log(
  JSON.stringify({
    cardTree: rows(loaded.labelTreeItems(options, labels)),
    appTree: rows(loaded.labelFacetItems(options, labels)),
    cardExpand: [...loaded.expandWithDescendants(['veh', 'bowl'], labels)].sort(),
    appExpand: [...loaded.appExpandWithDescendants(['veh', 'bowl'], labels)].sort(),
  })
);
