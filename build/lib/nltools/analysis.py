'''
    NeuroLearn Analysis Tools
    =========================
    These tools provide the ability to quickly run 
    machine-learning analyses on imaging data

    Author: Luke Chang
    License: MIT
'''

# ToDo
# 1) add roc functionality for classification
# 2) add thresholding functionality
# 3) add bootstrapping functionality
# 4) add tests
# 5) add within subject checks and plots
# 6) Plot probabilities

import os
import nibabel as nib
import sklearn
from nilearn.input_data import NiftiMasker
import pandas as pd
import numpy as np
from nilearn.plotting import *
import seaborn as sns    
import matplotlib.pyplot as plt
from nltools.plotting import dist_from_hyperplane_plot, scatterplot, probability_plot

# Paths
resource_dir = os.path.join(os.path.dirname(__file__),'resources')


class Predict:

    def __init__(self, data, Y, subject_id = None, algorithm=None, cv_dict=None, mask=None, 
                output_dir='.', **kwargs):
        """ Initialize Predict.
        Args:
            data: nibabel data instance
            Y: vector of training labels
            subject_id: vector of labels corresponding to each subject
            algorithm: Algorithm to use for prediction.  Must be one of 'svm', 'svr', 
                'linear', 'logistic', 'lasso', 'ridge', 'ridgeClassifier','randomforest', 
                or 'randomforestClassifier'
            cv_dict: Type of cross_validation to use. A dictionary of {'kfold',5} or 
                {'loso':subject_id}.
            mask: binary nibabel mask
            output_dir: Directory to use for writing all outputs
            **kwargs: Additional keyword arguments to pass to the prediction algorithm
        
        """
        self.output_dir = output_dir
        
        if subject_id is not None:
            self.subject_id = subject_id    

        if mask is not None:
            if type(mask) is not nib.nifti1.Nifti1Image:
                raise ValueError("mask is not a nibabel instance")
            self.mask = mask
        else:
            self.mask = nib.load(os.path.join(resource_dir,'MNI152_T1_2mm_brain_mask_dil.nii.gz'))
        
        if type(data) is not nib.nifti1.Nifti1Image:
            raise ValueError("data is not a nibabel instance")
        self.nifti_masker = NiftiMasker(mask_img=mask)
        self.data = self.nifti_masker.fit_transform(data)
        
        if self.data.shape[0]!= len(Y):
            raise ValueError("Y does not match the correct size of data")
        self.Y = Y

        if algorithm is not None:
            self.set_algorithm(algorithm, **kwargs)

        if cv_dict is not None:
            self.set_cv(cv_dict)
            

    def predict(self, algorithm=None, cv_dict=None, save_images=True, save_output=True, 
                save_plot = True, **kwargs):
        """ Run prediction
        Args:
            algorithm: Algorithm to use for prediction.  Must be one of 'svm', 'svr', 
                'linear', 'logistic', 'lasso', 'ridge', 'ridgeClassifier','randomforest', 
                or 'randomforestClassifier'
            cv_dict: Type of cross_validation to use. A dictionary of {'kfold',5} or 
                {'loso':subject_id}.
            save_images: Boolean indicating whether or not to save images to file.
            save_output: Boolean indicating whether or not to save prediction output to file.
            save_plot: Boolean indicating whether or not to create plots.
            **kwargs: Additional keyword arguments to pass to the prediction algorithm
        """
            
        if algorithm is not None:
            self.set_algorithm(algorithm, **kwargs)
        
        if self.algorithm is None:
            raise ValueError("Make sure you specify an 'algorithm' to use.")

        # Overall Fit for weight map
        predicter = self.predicter
        predicter.fit(self.data, self.Y)
        self.yfit = predicter.predict(self.data) # will be overwritten if xvalidating

        if save_images:
            self._save_image(predicter)

        # Cross-Validation Fit
        if cv_dict is not None:
            self.set_cv(cv_dict)    
        
        if hasattr(self,'cv'):
            
            predicter_cv = self.predicter
            
            if self.prediction_type is 'classification':
                if self.algorithm not in ['svm','ridgeClassifier','ridgeClassifierCV']:
                    self.prob = np.zeros(len(self.Y))
                else:
                    xval_dist_from_hyperplane = np.zeros(len(self.Y))
                    if self.algorithm is 'svm' and self.predicter.probability:
                        self.prob = np.zeros(len(self.Y))

            for train, test in self.cv:
                predicter_cv.fit(self.data[train], self.Y[train])
                self.yfit[test] = predicter_cv.predict(self.data[test])
            
                if self.prediction_type is 'classification':
                    if self.algorithm not in ['svm','ridgeClassifier','ridgeClassifierCV']:
                        self.prob[test] = predicter_cv.predict_proba(self.data[test])
                    else:
                        xval_dist_from_hyperplane[test] = predicter_cv.decision_function(self.data[test])
                        if self.algorithm is 'svm' and self.predicter.probability:
                            self.prob[test] = predicter_cv.predict_proba(self.data[test])
            
            if save_output:
                self.stats_output = pd.DataFrame({
                                    'SubID' : self.subject_id, 
                                    'Y' : self.Y, 
                                    'yfit' : self.yfit})
                    
                if self.prediction_type is 'classification':
                    if self.algorithm not in ['svm','ridgeClassifier','ridgeClassifierCV']:
                        self.stats_output['Probability'] = self.prob
                    else:
                        self.stats_output['xval_dist_from_hyperplane']=xval_dist_from_hyperplane
                        if self.algorithm is 'svm' and self.predicter.probability:
                            self.stats_output['Probability'] = self.prob                    
                self._save_stats_output()
                    
                if save_plot:
                    self._save_plot(predicter_cv)

        if self.prediction_type is 'classification':
            self.mcr = np.mean(self.yfit==self.Y)
            print 'overall CV accuracy: %.2f' % self.mcr
        elif self.prediction_type is 'prediction':
            self.rmse = np.sqrt(np.mean((self.yfit-self.Y)**2))
            self.r = np.corrcoef(self.Y,self.yfit)[0,1]
            print 'overall Root Mean Squared Error: %.2f' % self.rmse
            print 'overall Correlation: %.2f' % self.r


    def set_algorithm(self, algorithm, **kwargs):
        """ Set the algorithm to use in subsequent prediction analyses.
        Args:
            algorithm: The prediction algorithm to use. Either a string or an (uninitialized)
                scikit-learn prediction object. If string, must be one of 'svm', 'svr', 
                'linear', 'logistic', 'lasso', 'ridge', 'ridgeClassifier','randomforest', 
                or 'randomforestClassifier'
            kwargs: Additional keyword arguments to pass onto the scikit-learn clustering
                object.
        """

        self.algorithm = algorithm

        if isinstance(algorithm, basestring):
            
            algs_classify = ['svm','logistic','ridgeClassifier','ridgeClassifierCV','randomforestClassifier']
            algs_predict = ['svr','linear','lasso','lassoCV','ridge','ridgeCV','randomforest']

            if algorithm in algs_classify:
                self.prediction_type = 'classification'
            elif algorithm in algs_predict:
                self.prediction_type = 'prediction'
            else:
                raise ValueError("Invalid prediction/classification algorithm name. Valid " +
                    "options are 'svm','svr', 'linear', 'logistic', 'lasso', 'ridge', " +
                    "'ridgeClassifier', 'randomforest', or 'randomforestClassifier'.")

            # Not particularly happy with this code.
            # Unfortunately, Dictionary method wasn't able to load the modules correctly
            if self.algorithm == 'svm':
                from sklearn.svm import SVC
                self.predicter = SVC(**kwargs)
            elif self.algorithm == 'svr':
                from sklearn.svm import SVR
                self.predicter = SVR(**kwargs)
            elif self.algorithm == 'linear':
                from sklearn.linear_model import LinearRegression
                self.predicter = LinearRegression(**kwargs)
            elif self.algorithm == 'logistic':
                from sklearn.linear_model import LogisticRegression
                self.predicter = LogisticRegression(**kwargs)
            elif self.algorithm == 'ridge':
                from sklearn.linear_model import Ridge
            elif self.algorithm == 'ridgeCV':
                from sklearn.linear_model import RidgeCV
                self.predicter = RidgeCV(**kwargs)
            elif self.algorithm == 'ridgeClassifier':
                from sklearn.linear_model import RidgeClassifier
                self.predicter = RidgeClassifier(**kwargs)
            elif self.algorithm == 'ridgeClassifierCV':
                from sklearn.linear_model import RidgeClassifierCV
                self.predicter = RidgeClassifierCV(**kwargs)
            elif self.algorithm == 'lasso':
                from sklearn.linear_model import Lasso
            elif self.algorithm == 'lassoCV':
                from sklearn.linear_model import LassoCV
                self.predicter = LassoCV(**kwargs)
            elif self.algorithm == 'randomforestClassifier':
                from sklearn.ensemble import RandomForestClassifier
                self.predicter = RandomForestClassifier(**kwargs)
            elif self.algorithm == 'randomforest':
                from sklearn.ensemble import RandomForestRegressor
                self.predicter = RandomForestRegressor(**kwargs)


    def set_cv(self, cv_dict):
        """ Set the CV algorithm to use in subsequent prediction analyses.
        Args:
            cv_dict: Type of cross_validation to use. A dictionary of {'kfold',5} or {'loso':subject_id}.
        """

        if type(cv_dict) is dict:
            if cv_dict.keys()[0] is 'kfolds':
                from  sklearn.cross_validation import StratifiedKFold
                self.cv = StratifiedKFold(self.Y, n_folds=cv_dict.values()[0])
            elif cv_dict.keys()[0] is 'loso':
                from sklearn.cross_validation import LeaveOneLabelOut
                self.cv = LeaveOneLabelOut(labels=cv_dict.values()[0])
            else:
                raise ValueError("Make sure you specify a dictionary of {'kfold',5} or {'loso':subject_id}.")
        else:
            raise ValueError("Make sure 'cv_dict' is a dictionary.")


    def _save_image(self, predicter):
        """ Write out weight map to Nifti image. 
        Args:
            predicter: predicter instance
        Outputs:
            predicter_weightmap.nii.gz: Will output a nifti image of weightmap
        """

        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)

        coef_img = self.nifti_masker.inverse_transform(predicter.coef_)
        nib.save(coef_img, os.path.join(self.output_dir, self.algorithm + '_weightmap.nii.gz'))


    def _save_stats_output(self):
        """ Write stats output to csv file. 
        Args:
            stats_output: a pandas file with prediction output
        Outputs:
            predicter_stats_output.csv: Will output a csv file of stats output
        """

        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)
        self.stats_output.to_csv(os.path.join(self.output_dir, self.algorithm + '_Stats_Output.csv'))


    def _save_plot(self, predicter):
        """ Save Plots. 
        Args:
            predicter: predicter instance
        Outputs:
            predicter_weightmap_montage.png: Will output a montage of axial slices of weightmap
            predicter_prediction.png: Will output a plot of prediction
        """

        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)
        
        coef_img = self.nifti_masker.inverse_transform(predicter.coef_)
        overlay_img = nib.load(os.path.join(resource_dir,'MNI152_T1_2mm_brain.nii.gz'))

        fig1 = plot_stat_map(coef_img, overlay_img, title=self.algorithm + " weights", 
                            cut_coords=range(-40, 40, 10), display_mode='z')
        fig1.savefig(os.path.join(self.output_dir, self.algorithm + '_weightmap_axial.png'))

        if self.prediction_type == 'classification':
            if self.algorithm not in ['svm','ridgeClassifier','ridgeClassifierCV']:
                fig2 = probability_plot(self.stats_output)
                fig2.savefig(os.path.join(self.output_dir, self.algorithm + '_prob_plot.png'))
            else:
                fig2 = dist_from_hyperplane_plot(self.stats_output)
                fig2.savefig(os.path.join(self.output_dir, self.algorithm + 
                            '_xVal_Distance_from_Hyperplane.png'))
                if self.algorithm is 'svm' and self.predicter.probability:
                    fig3 = probability_plot(self.stats_output)
                    fig3.savefig(os.path.join(self.output_dir, self.algorithm + '_prob_plot.png'))

        elif self.prediction_type == 'prediction':
            fig2 = scatterplot(self.stats_output)
            fig2.savefig(os.path.join(self.output_dir, self.algorithm + '_scatterplot.png'))

def apply_mask(data=None, Y=None, weight_map=None, mask=None, subject_id=None, method='dot_product', 
                save_output=True, save_plot=True,output_dir='.', **kwargs):
    """ Apply Nifti weight map to Nifti Images. 
        Args:
            data: nibabel instance of data to be applied
            Y: vector of training labels
            weight_map: nibabel instance of weight map
            mask: binary nibabel mask
            subject_id: vector of labels corresponding to each subject
            method: type of pattern expression (e.g,. 'dot_product','correlation')
            save_output: Save pattern expression values to csv file
            save_plot: Boolean indicating whether or not to create plots.
            output_dir: Directory to use for writing all outputs
            **kwargs: Additional parameters to pass
        Outputs:
            pexp: Outputs a vector of pattern expression values
    """ 

    if mask is not None:
        if type(mask) is not nib.nifti1.Nifti1Image:
            raise ValueError("Mask is not a nibabel instance")
    else:
        mask = nib.load(os.path.join(resource_dir,'MNI152_T1_2mm_brain_mask_dil.nii.gz'))
    
    if type(data) is not nib.nifti1.Nifti1Image:
        raise ValueError("Data is not a nibabel instance")
    
    nifti_masker = NiftiMasker(mask_img=mask)
    
    data_masked = nifti_masker.fit_transform(data)

    if type(weight_map) is not nib.nifti1.Nifti1Image:
        raise ValueError("Weight_map is not a nibabel instance")
    
    weight_map_masked = nifti_masker.fit_transform(weight_map)

    # Calculate pattern expression
    pexp = np.dot(data_masked,np.transpose(weight_map_masked))
    stats_output = pd.DataFrame({
                                'SubID' : subject_id, 
                                'Y' : Y, 
                                'xval_dist_from_hyperplane' : pexp[:,0]})
    if save_output:
        stats_output.to_csv(os.path.join(output_dir, 'Pexp_' + method + '_Stats_Output.csv'))

    # Display results
    if save_plot:
        fig2 = dist_from_hyperplane_plot(stats_output)
        fig2.savefig(output_dir + '/Pattern_Expression_by_Subject_' + method + '.png')

    return pexp
