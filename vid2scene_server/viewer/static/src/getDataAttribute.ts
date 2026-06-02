export function getDataAttribute(key: string) {
    return document.getElementById('app')?.getAttribute(`data-${key}`);
}