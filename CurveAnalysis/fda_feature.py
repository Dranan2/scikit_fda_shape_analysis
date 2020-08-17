import numpy as np
from skfda.representation.basis import BSpline, FDataBasis
from skfda.representation.grid import FDataGrid
from matplotlib import pyplot as plt
from skfda.preprocessing.smoothing import BasisSmoother
from skfda.preprocessing.smoothing.validation import SmoothingParameterSearch, LinearSmootherGeneralizedCVScorer
from tqdm.notebook import tqdm
from scipy.integrate import simps
from numpy.linalg import norm
from itertools import combinations 

def _calculate_velocity(DX1):
    return [norm(dxi) for dxi in DX1.T]


def _calculate_arc_length(DX1, t):
    n = len(t)
    t0 = t[0]
    v = _calculate_velocity(DX1)
    v0 = v[0]
    return [simps(y=v[:i+1], x=t[:i+1]) for i in range(n)]


def _calculate_curvature(DX1, DX2):
    def norm2(x):
        # return the squared L2 norm
        return norm(x)**2
    n = DX1.shape[1]
    res = [norm2(DX1[:, i])*norm2(DX2[:, i]) -
           np.square(DX1[:, i].dot(DX2[:, i])) for i in range(n)]

    return [np.sqrt(res[i])/(norm(DX1[:, i])**3) for i in range(n)]


class CurveAnalysis:

    def __init__(self, grid: FDataGrid):
        self.init_grid = grid.copy()
        self.sample_points = self.init_grid.sample_points[0]
        self._nSeries = self.init_grid.data_matrix.shape[0]
        self._nObs = self.init_grid.data_matrix.shape[1]
        self._nVar = self.init_grid.data_matrix.shape[2]
        self.coordinates_grids = list(self.init_grid.coordinates)
        self._smoothed = False
        self._scaled = False

    def smooth_grids(self,
                     param_values: list = None,
                     smoother=None,
                     scorer=LinearSmootherGeneralizedCVScorer()):
        '''
            Search hyperparameter of user's estimator, then transform datagrid with it
            If no param_values specified, algorithm will try 100 values between 10**-8 et 10**8
            smoother must be either a skfda.BasisSmoother or a list of skfda.BasisSmoother one by variable
        '''
        if param_values is None:
            param_values = np.logspace(-8, 8, num=100)
        if smoother is None:
            print("Default Smoother used")
            smoother = BasisSmoother(
                BSpline(domain_range=self.domain_range, n_basis=15, order=6))
        if isinstance(smoother, list) or isinstance(smoother, np.ndarray):
            if len(smoother) != self._nVar:
                raise ValueError(
                    "number of smoothers must be equal to the number of variable or equal to 1")
        else:
            smoother.domain_range = self.init_grid.domain_range
            smoother = [smoother]*self._nVar

        smoothed_grids = []
        print("Smoothing data...")

        for i in tqdm(range(self._nVar)):
            data_grid = self.coordinates_grids[i]
            grid_search = SmoothingParameterSearch(estimator=smoother[i],
                                                   param_values=param_values,
                                                   scoring=scorer)
            _ = grid_search.fit(data_grid)
            best_est = grid_search.best_estimator_
            smoothed_grids.append(best_est.fit_transform(data_grid))
        print("Smoothing Done")
        self.coordinates_grids = smoothed_grids
        self._smoothed = True
        self.coordinates_grids_dx1 = [grid.derivative(
            1) for grid in self.coordinates_grids]
        self.coordinates_grids_dx2 = [grid.derivative(
            2) for grid in self.coordinates_grids]
        return None

    def scale_grids(self, axis=0, with_std=False):
        '''
            Perform scaling for each time series for each variables
            if axis=0 it will minus each time series by its mean,else it will minus
            every timestep by the mean of each time series evaluated at that timestep
        '''
        if self._scaled == True:
            print("Data was already scaled, no additionnal scale done")
            return

        def _scale(x, with_std=False):
            xi = np.array(x)
            mean = np.mean(xi)
            if with_std:
                sd = np.std(xi)
                return (xi-mean)/sd
            else:
                return xi-mean
        if axis > 1:
            raise ValueError("axis should be either 0 or 1")

        for grid in self.coordinates_grids:
            for i in range(grid.data_matrix.shape[axis]):
                if axis == 0:
                    grid.data_matrix[i, :, 0] = _scale(
                        grid.data_matrix[i, :, 0], with_std=with_std)
                else:
                    grid.data_matrix[:, i, 0] = _scale(
                        grid.data_matrix[:, i, 0], with_std=with_std)
            grid = FDataGrid(data_matrix=grid.data_matrix,
                             sample_points=self.sample_points,
                             domain_range=grid.domain_range,
                             dataset_label=grid.dataset_label)
        self._scaled = True
        return None

    def compute_velocity(self):

        if not self._smoothed:
            _ = self.smooth_grids()
        dx1_mat = np.empty([self._nVar, self._nObs])
        result_matrix = np.empty([self._nSeries, self._nObs])
        for i in range(self._nSeries):
            for j in range(self._nVar):
                dx1_mat[j, :] = self.coordinates_grids_dx1[j].data_matrix[i, :, 0]
            result_matrix[i, :] = _calculate_velocity(DX1=dx1_mat)
        return FDataGrid(data_matrix=result_matrix,
                         sample_points=self.sample_points, dataset_label="velocity")

    def compute_arc_length(self):
        if not self._smoothed:
            _ = self.smooth_grids()
        dx1_mat = np.empty([self._nVar, self._nObs])
        result_matrix = np.empty([self._nSeries, self._nObs])
        for i in range(self._nSeries):
            for j in range(self._nVar):
                dx1_mat[j, :] = self.coordinates_grids_dx1[j].data_matrix[i, :, 0]
            result_matrix[i, :] = _calculate_arc_length(
                DX1=dx1_mat, t=self.sample_points)
        return FDataGrid(data_matrix=result_matrix,
                         sample_points=self.sample_points, dataset_label="arc_length")

    def compute_curvature(self):

        if not self._smoothed:
            _ = self.smooth_grids()
        dx1_mat = np.empty([self._nVar, self._nObs])
        dx2_mat = np.empty([self._nVar, self._nObs])
        result_matrix = np.empty([self._nSeries, self._nObs])
        for i in range(self._nSeries):
            for j in range(self._nVar):
                dx1_mat[j, :] = self.coordinates_grids_dx1[j].data_matrix[i, :, 0]
                dx2_mat[j, :] = self.coordinates_grids_dx2[j].data_matrix[i, :, 0]
            result_matrix[i, :] = _calculate_curvature(
                DX1=dx1_mat, DX2=dx2_mat)
        return FDataGrid(data_matrix=result_matrix,
                         sample_points=self.sample_points, dataset_label="curvature")

    def plot_grids(self):
        '''
            One plot by variable (i.e. dimension)
            In each plot all time series are plotted
        '''
        for j in range(self._nVar):
            labels = self.init_grid.coordinates[j].axes_labels
            fig, ax = plt.subplots()
            for i in range(self._nSeries):
                ax.plot(self.sample_points,
                        self.coordinates_grids[j].data_matrix[i, :, 0])
            if labels is not None:
                ax.set_xlabel(labels[0])
                ax.set_ylabel(labels[1])
            plt.show()

    def plot_interaction(self):
        '''
            Plot interaction between variables 2 by 2
        '''
        if self._nVar < 2:
            raise ValueError("Can only plot multivariate data")
        else:
            combinaisons = [comb for comb in combinations(
                np.arange(self._nVar), 2)]
            for comb in combinaisons:
                fig, ax = plt.subplots()
                for i in range(self._nSeries):
                    ax.plot(self.coordinates_grids[comb[0]].data_matrix[i, :, 0],
                            self.coordinates_grids[comb[1]].data_matrix[i, :, 0])
                ax.set_xlabel("Variable "+str(comb[0]))
                ax.set_ylabel("Variable "+str(comb[1]))
                ax.set_title("Interacton between variable " +
                             str(comb[0])+" with variable "+str(comb[1]))
                plt.show()