import { fetcher } from '@/lib/coingecko.actions';
import CategoriesTable from './CategoriesTable';
import { CategoriesFallback } from './fallback';
import type { Category } from '@/type';

const Categories = async () => {
  let categories: Category[] | null = null;

  try {
    categories = await fetcher<Category[]>('/coins/categories');
  } catch {
    return <CategoriesFallback />;
  }

  return (
    <div id="categories" className="custom-scrollbar">
      <h4>Top Categories</h4>
      <CategoriesTable categories={categories} />
    </div>
  );
};

export default Categories;
