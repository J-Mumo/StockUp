import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { ArrowLeft } from 'lucide-react';
import toast from 'react-hot-toast';
import { stocksApi } from '../lib/services';
import type { FinancialStatement } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

interface FinancialFormData {
  statement_type: 'income' | 'balance_sheet' | 'cash_flow';
  period_type: 'annual' | 'quarterly';
  report_date: string;
  revenue: string;
  net_income: string;
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  operating_cash_flow: string;
  capital_expenditures: string;
  free_cash_flow: string;
  earnings_per_share: string;
  dividends_per_share: string;
}

const incomeFields = [
  { name: 'revenue', label: 'Revenue' },
  { name: 'cost_of_revenue', label: 'Cost of Revenue' },
  { name: 'gross_profit', label: 'Gross Profit' },
  { name: 'operating_income', label: 'Operating Income' },
  { name: 'net_income', label: 'Net Income' },
  { name: 'earnings_per_share', label: 'Earnings Per Share' },
  { name: 'dividends_per_share', label: 'Dividends Per Share' },
];

const balanceFields = [
  { name: 'total_assets', label: 'Total Assets' },
  { name: 'total_liabilities', label: 'Total Liabilities' },
  { name: 'total_equity', label: 'Total Equity' },
  { name: 'cash_and_equivalents', label: 'Cash & Equivalents' },
  { name: 'total_debt', label: 'Total Debt' },
  { name: 'book_value_per_share', label: 'Book Value Per Share' },
];

const cashFlowFields = [
  { name: 'operating_cash_flow', label: 'Operating Cash Flow' },
  { name: 'capital_expenditures', label: 'Capital Expenditures' },
  { name: 'free_cash_flow', label: 'Free Cash Flow' },
  { name: 'investing_cash_flow', label: 'Investing Cash Flow' },
  { name: 'financing_cash_flow', label: 'Financing Cash Flow' },
];

function inferStatementType(statement: FinancialStatement): FinancialFormData['statement_type'] {
  const hasCashFlow = statement.operating_cash_flow !== null || statement.capital_expenditures !== null || statement.free_cash_flow !== null;
  if (hasCashFlow) return 'cash_flow';

  const hasBalanceSheet =
    statement.total_assets !== null ||
    statement.total_liabilities !== null ||
    statement.total_equity !== null ||
    statement.shareholders_equity !== null;
  if (hasBalanceSheet) return 'balance_sheet';

  return 'income';
}

export default function FinancialEntryPage() {
  const { id, financialId } = useParams<{ id: string; financialId?: string }>();
  const companyId = Number(id);
  const isEdit = !!financialId;
  const navigate = useNavigate();

  const [loading, setLoading] = useState(isEdit);
  const [submitting, setSubmitting] = useState(false);
  const [existingData, setExistingData] = useState<FinancialStatement | null>(null);

  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<FinancialFormData>({
    defaultValues: {
      statement_type: 'income',
      period_type: 'annual',
      report_date: new Date().toISOString().split('T')[0],
    },
  });

  const statementType = watch('statement_type');

  useEffect(() => {
    if (isEdit && financialId) {
      stocksApi.getFinancials(companyId)
        .then((res) => {
          const found = res.data.find((f) => f.id === Number(financialId));
          if (found) {
            setExistingData(found);
            setValue('statement_type', inferStatementType(found));
            setValue('period_type', found.period_type as 'annual' | 'quarterly');
            setValue('report_date', found.report_date ? found.report_date.slice(0, 10) : new Date().toISOString().split('T')[0]);

            const formKeys: Array<keyof FinancialFormData> = [
              'revenue',
              'net_income',
              'total_assets',
              'total_liabilities',
              'total_equity',
              'operating_cash_flow',
              'capital_expenditures',
              'free_cash_flow',
              'earnings_per_share',
              'dividends_per_share',
            ];

            formKeys.forEach((key) => {
              const value = found[key as keyof FinancialStatement];
              if (value !== null && value !== undefined) {
                setValue(key, String(value));
              }
            });
          }
        })
        .catch(() => toast.error('Failed to load financial data'))
        .finally(() => setLoading(false));
    }
  }, [isEdit, financialId, companyId, setValue]);

  const getFields = () => {
    switch (statementType) {
      case 'income': return incomeFields;
      case 'balance_sheet': return balanceFields;
      case 'cash_flow': return cashFlowFields;
      default: return incomeFields;
    }
  };

  const onSubmit = async (formData: FinancialFormData) => {
    setSubmitting(true);
    const fields = getFields();
    const payload: Record<string, number | string | null> = {
      fiscal_year: Number(formData.report_date.slice(0, 4)),
      period_type: formData.period_type,
      report_date: formData.report_date,
    };

    fields.forEach((f) => {
      const val = (formData as unknown as Record<string, string>)[f.name];
      payload[f.name] = val ? Number(val) : null;
    });

    try {
      if (isEdit && financialId) {
        await stocksApi.updateFinancial(companyId, Number(financialId), payload as Partial<FinancialStatement>);
        toast.success('Financial statement updated');
      } else {
        await stocksApi.createFinancial(companyId, payload as Partial<FinancialStatement>);
        toast.success('Financial statement created');
      }
      navigate(`/companies/${companyId}`);
    } catch {
      toast.error('Failed to save financial statement');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <PageLoader />;

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link to={`/companies/${companyId}`} className="p-2 hover:bg-dark-surface rounded-lg transition-colors">
          <ArrowLeft className="text-gray-400" size={20} />
        </Link>
        <h1 className="text-2xl font-bold text-white">
          {isEdit ? 'Edit' : 'New'} Financial Statement
        </h1>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="bg-dark-surface border border-dark-border rounded-xl p-6">
        {/* Type & Period */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Statement Type</label>
            <select
              {...register('statement_type', { required: true })}
              disabled={isEdit}
              className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="income">Income Statement</option>
              <option value="balance_sheet">Balance Sheet</option>
              <option value="cash_flow">Cash Flow</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Period Type</label>
            <select
              {...register('period_type', { required: true })}
              className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="annual">Annual</option>
              <option value="quarterly">Quarterly</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Period End Date</label>
            <input
              type="date"
              {...register('report_date', { required: 'Required' })}
              className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            {errors.report_date && (
              <p className="text-red-400 text-sm mt-1">{errors.report_date.message}</p>
            )}
          </div>
        </div>

        {/* Financial Fields */}
        <div className="border-t border-dark-border pt-6">
          <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
            {statementType === 'income' && 'Income Statement Data'}
            {statementType === 'balance_sheet' && 'Balance Sheet Data'}
            {statementType === 'cash_flow' && 'Cash Flow Data'}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {getFields().map((field) => (
              <div key={field.name}>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  {field.label}
                </label>
                <input
                  type="number"
                  step="any"
                  {...register(field.name as keyof FinancialFormData)}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="0.00"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Submit */}
        <div className="mt-6 flex gap-3 justify-end">
          <Link
            to={`/companies/${companyId}`}
            className="px-4 py-2.5 border border-dark-border text-gray-300 rounded-lg hover:bg-dark-border/50 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white font-medium rounded-lg transition-colors"
          >
            {submitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
